import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import timedelta
import time

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
st.set_page_config(
    page_title="Agentic Production Planning System",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom Colors
COLORS = {
    "healthy": "#00C896",
    "warning": "#FFA500",
    "critical": "#FF4C4C",
    "info": "#4A9EFF",
    "background": "#0E1117"
}

# ==========================================
# 📦 DATA LOADING
# ==========================================
@st.cache_data
def load_data():
    # Load the CSV file
    try:
        df = pd.read_csv("data.csv")
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        df = df.sort_values(by='Timestamp').reset_index(drop=True)
        return df
    except Exception as e:
        df = pd.DataFrame(columns=[
            'Timestamp','Order_ID','Product_Category','Region','Assigned_Facility','Production_Line',
            'Forecasted_Demand','Actual_Order_Qty','Workforce_Required','Workforce_Deployed',
            'Schedule_Status','Operator_Override_Flag','Machine_Temperature_C','Machine_Vibration_Hz',
            'Predicted_Time_To_Failure_Hrs','Machine_OEE_Pct','Raw_Material_Inventory_Units',
            'Inventory_Threshold','Procurement_Action','Live_Supplier_Quote_USD','Grid_Pricing_Period',
            'Energy_Consumed_kWh','Carbon_Emissions_kg','Carbon_Cost_Penalty_USD'
        ])
        st.error(f"Failed to load data.csv: {e}")
        return df

df_full = load_data()

# ==========================================
# 🧠 STATE MANAGEMENT (SIMULATION)
# ==========================================
if 'time_cursor' not in st.session_state:
    st.session_state.time_cursor = min(100, len(df_full)) # Start with 100 rows

if 'agent_log' not in st.session_state:
    st.session_state.agent_log = pd.DataFrame(columns=[
        'logged_at', 'agent_name', 'severity', 'order_id', 'facility', 'message', 'confidence_pct', 'action_taken'
    ])

def advance_time(steps=10):
    if st.session_state.time_cursor + steps <= len(df_full):
        st.session_state.time_cursor += steps
    else:
        st.session_state.time_cursor = len(df_full)

def log_agent_event(agent_name, severity, order_id, facility, message, confidence_pct, action_taken):
    new_log = pd.DataFrame([{
        'logged_at': pd.Timestamp.now(),
        'agent_name': agent_name,
        'severity': severity,
        'order_id': order_id,
        'facility': facility,
        'message': message,
        'confidence_pct': confidence_pct,
        'action_taken': action_taken
    }])
    st.session_state.agent_log = pd.concat([new_log, st.session_state.agent_log], ignore_index=True)
    if len(st.session_state.agent_log) > 500:
        st.session_state.agent_log = st.session_state.agent_log.head(500)

# Simulate streaming data based on cursor
df = df_full.iloc[:st.session_state.time_cursor].copy()
current_time = df['Timestamp'].max() if not df.empty else pd.Timestamp.now()

# ==========================================
# 🤖 MULTI-AGENT LOGIC
# ==========================================
def run_agents():
    if df.empty: return
    
    # Analyze the latest batch (e.g., last 10 rows)
    latest_batch = df.tail(10)
    
    for _, row in latest_batch.iterrows():
        order_id = row['Order_ID']
        facility = row['Assigned_Facility']
        
        # 1. Forecaster Agent
        if row['Actual_Order_Qty'] > row['Forecasted_Demand'] * 1.30:
            msg = f"Demand spike detected! Actual ({row['Actual_Order_Qty']}) > 1.3x Forecast ({row['Forecasted_Demand']})."
            log_agent_event('Forecaster', 'WARNING', order_id, facility, msg, 85.0, "Flagged order for spike review")
            
        # 2. Mechanic Agent
        if row['Predicted_Time_To_Failure_Hrs'] < 24:
            msg = f"Imminent failure predicted in {row['Predicted_Time_To_Failure_Hrs']:.1f} hrs. Temp: {row['Machine_Temperature_C']:.1f}C"
            log_agent_event('Mechanic', 'CRITICAL', order_id, facility, msg, 92.5, "Triggered emergency maintenance")
        elif row['Predicted_Time_To_Failure_Hrs'] < 100:
            msg = f"Watch TTF: {row['Predicted_Time_To_Failure_Hrs']:.1f} hrs."
            log_agent_event('Mechanic', 'WARNING', order_id, facility, msg, 70.0, "Schedule inspection")
            
        # 3. Buyer Agent
        if row['Raw_Material_Inventory_Units'] < row['Inventory_Threshold']:
            msg = f"Inventory low ({row['Raw_Material_Inventory_Units']} < {row['Inventory_Threshold']})."
            log_agent_event('Buyer', 'WARNING', order_id, facility, msg, 99.0, "Initiate auto-order")
            
        # 4. Environmentalist Agent
        if row['Grid_Pricing_Period'] == 'Peak' and row['Carbon_Cost_Penalty_USD'] > 300:
            msg = f"High Carbon Penalty during Peak: ${row['Carbon_Cost_Penalty_USD']}."
            log_agent_event('Environmentalist', 'WARNING', order_id, facility, msg, 88.0, "Suggest schedule reroute")

    # 5. Orchestrator Agent (Combines signals)
    # Check if any recent critical events
    recent_critical = st.session_state.agent_log.head(10)
    critical_events = recent_critical[recent_critical['severity'] == 'CRITICAL']
    if not critical_events.empty:
        for idx, crit_row in critical_events.iterrows():
            if 'emergency maintenance' in crit_row['action_taken']:
                msg = f"Orchestrating response to Mechanic critical alert at {crit_row['facility']}."
                log_agent_event('Orchestrator', 'CRITICAL', crit_row['order_id'], crit_row['facility'], msg, 95.0, "Rerouting orders to alternate line")
                break # Just log one orchestrator action per tick to avoid spam

# Run agents on the current state
run_agents()

# ==========================================
# 📊 PAGE 1: COMMAND CENTER
# ==========================================
def render_command_center():
    st.title("🏭 Command Center")
    st.markdown("Real-time oversight of all production facilities and AI agent activities.")
    
    # KPI Row
    col1, col2, col3, col4, col5 = st.columns(5)
    
    if not df.empty:
        on_time_pct = (df['Schedule_Status'] == 'On-Time').mean() * 100
        active_alerts = len(st.session_state.agent_log[st.session_state.agent_log['severity'] != 'INFO'])
        last_24h = df[df['Timestamp'] >= current_time - timedelta(hours=24)]
        carbon_penalty = last_24h['Carbon_Cost_Penalty_USD'].sum() if not last_24h.empty else 0
        workforce_cov = (df['Workforce_Deployed'].sum() / df['Workforce_Required'].sum() * 100) if df['Workforce_Required'].sum() > 0 else 0
        
        inventory_med = df['Raw_Material_Inventory_Units'].median()
        consumption_est = df['Actual_Order_Qty'].median() * 12 # Rough daily est
        inv_days = inventory_med / consumption_est if consumption_est > 0 else 0
        
        col1.metric("On-Time Delivery", f"{on_time_pct:.1f}%", f"{(on_time_pct - 90):.1f}% vs Target")
        col2.metric("Active Alerts", active_alerts)
        col3.metric("Carbon Penalty (24h)", f"${carbon_penalty:,.0f}")
        col4.metric("Inv. Days Remaining", f"{inv_days:.1f} days")
        col5.metric("Workforce Coverage", f"{workforce_cov:.1f}%")
        
    st.markdown("---")
    
    # Facility Cards
    st.subheader("🌐 Facility Status")
    facilities = df['Assigned_Facility'].unique() if not df.empty else []
    
    if len(facilities) > 0:
        cols = st.columns(min(len(facilities), 5))
        for i, fac in enumerate(facilities[:5]):
            fac_df = df[df['Assigned_Facility'] == fac]
            oee = fac_df['Machine_OEE_Pct'].mean()
            status_color = COLORS['healthy'] if oee > 90 else COLORS['warning'] if oee > 80 else COLORS['critical']
            
            with cols[i]:
                st.markdown(f"""
                <div style="border:1px solid #444; border-top:4px solid {status_color}; border-radius:5px; padding:15px; background-color: #1E1E1E;">
                    <h5 style="margin-top:0;">{fac.split(' - ')[0]}</h5>
                    <p style="margin:0; font-size:14px; color:#AAA;">OEE: <b>{oee:.1f}%</b></p>
                    <p style="margin:0; font-size:14px; color:#AAA;">Type: {fac.split(' - ')[1] if ' - ' in fac else 'Unknown'}</p>
                </div>
                """, unsafe_allow_html=True)
                
    st.markdown("---")
    
    # Agent Log
    st.subheader("🕵️‍♂️ Live Agent Activity Log")
    if not st.session_state.agent_log.empty:
        # Style the dataframe
        def color_severity(val):
            color = COLORS['healthy']
            if val == 'WARNING': color = COLORS['warning']
            elif val == 'CRITICAL': color = COLORS['critical']
            return f'color: {color}; font-weight: bold;'
            
        styled_df = st.session_state.agent_log.head(50).style.map(color_severity, subset=['severity'])
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.info("No agent activity logged yet.")

# ==========================================
# 📊 PAGE 2: DEMAND INTELLIGENCE
# ==========================================
def render_demand_intelligence():
    st.title("📈 Demand Intelligence (Forecaster Agent)")
    if df.empty: return st.warning("No data available.")
    
    st.markdown("Analyzing deviations between forecasted demand and actual orders.")
    
    # Aggregation
    daily_demand = df.set_index('Timestamp').resample('D').agg({
        'Forecasted_Demand': 'sum',
        'Actual_Order_Qty': 'sum'
    }).reset_index()
    
    # Chart: Forecast vs Actual
    fig = px.line(daily_demand, x='Timestamp', y=['Forecasted_Demand', 'Actual_Order_Qty'],
                  labels={'value': 'Units', 'variable': 'Metric'},
                  title="Demand Trend: Forecast vs Actual",
                  color_discrete_sequence=[COLORS['info'], COLORS['warning']])
    st.plotly_chart(fig, use_container_width=True)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("⚠️ Demand Anomalies")
        anomalies = df[df['Actual_Order_Qty'] > df['Forecasted_Demand'] * 1.30]
        if not anomalies.empty:
            st.metric("Total Anomalies Detected", len(anomalies))
            st.dataframe(anomalies[['Timestamp', 'Order_ID', 'Product_Category', 'Forecasted_Demand', 'Actual_Order_Qty']], use_container_width=True)
        else:
            st.success("No significant demand anomalies detected.")
            
    with col2:
        st.subheader("🌍 Demand by Region")
        region_demand = df.groupby('Region')['Actual_Order_Qty'].sum().reset_index()
        fig_pie = px.pie(region_demand, names='Region', values='Actual_Order_Qty', hole=0.4)
        st.plotly_chart(fig_pie, use_container_width=True)

# ==========================================
# 📊 PAGE 3: PRODUCTION SCHEDULE
# ==========================================
def render_production_schedule():
    st.title("🗓️ Production Schedule (Orchestrator Agent)")
    if df.empty: return st.warning("No data available.")
    
    st.markdown("Dynamic scheduling and workforce allocation.")
    
    col1, col2, col3 = st.columns(3)
    wf_slider = col1.slider("Workforce Availability %", 50, 100, 95)
    cap_slider = col2.slider("Capacity Limit %", 50, 100, 100)
    priority = col3.selectbox("Optimization Priority", ["Time", "Cost", "Carbon Emissions"])
    
    st.subheader("Production Timeline")
    # Simulate a Gantt chart using the last 50 orders
    gantt_data = df.tail(50).copy()
    gantt_data['Finish'] = gantt_data['Timestamp'] + pd.Timedelta(hours=2)
    
    # Color map
    color_map = {
        'On-Time': COLORS['healthy'],
        'Delayed': COLORS['critical'],
        'Rerouted': COLORS['info'],
        'Maintenance Reroute': COLORS['warning']
    }
    
    fig = px.timeline(gantt_data, x_start="Timestamp", x_end="Finish", y="Assigned_Facility", color="Schedule_Status",
                      hover_data=['Order_ID', 'Product_Category'],
                      color_discrete_map=color_map, title="Recent/Active Production Runs")
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True)
    
    with st.expander("🤖 Orchestrator Agent Reasoning"):
        orch_logs = st.session_state.agent_log[st.session_state.agent_log['agent_name'] == 'Orchestrator']
        if not orch_logs.empty:
            for _, row in orch_logs.head(10).iterrows():
                st.write(f"**{row['logged_at'].strftime('%Y-%m-%d %H:%M:%S')}** | {row['facility']}")
                st.info(f"Reason: {row['message']} ➔ Action: {row['action_taken']}")
        else:
            st.write("No recent orchestrator actions.")

# ==========================================
# 📊 PAGE 4: DIGITAL TWIN SIMULATION
# ==========================================
def render_digital_twin():
    st.title("🧬 Digital Twin Simulation")
    if df.empty: return st.warning("No data available.")
    
    st.markdown("Simulate the impact of facility downtime or disruptions.")
    
    fac_list = df['Assigned_Facility'].unique().tolist()
    
    col1, col2 = st.columns(2)
    with col1:
        target_fac = st.selectbox("Select Facility for Simulation", fac_list)
    with col2:
        offline_hrs = st.number_input("Simulate Offline Duration (Hours)", min_value=2, max_value=72, value=12, step=2)
        
    if st.button("🔌 Run Simulation"):
        # Simple simulation logic
        fac_df = df[df['Assigned_Facility'] == target_fac].copy()
        
        affected_rows = int(offline_hrs / 2) # 2 hr cadence
        impact_qty = fac_df.tail(affected_rows)['Actual_Order_Qty'].sum() if not fac_df.empty else 0
        cost_delta = impact_qty * 5.0 # Assuming $5 delay penalty per unit
        
        st.subheader("Simulation Results")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Current Throughput Avg", f"{df['Actual_Order_Qty'].mean():.0f} / period")
        c2.metric("Simulated Impact (Units)", f"-{impact_qty:,.0f}", variant_color="normal", delta_color="inverse")
        c3.metric("Cost Delta Penalty", f"+${cost_delta:,.0f}", delta_color="inverse")
        
        st.markdown("### AI Recommendation")
        st.info("💡 **Orchestrator Suggestion:** Reroute standard line products to Partner Overflow facilities to mitigate 60% of the delay cost. Requires approval.")

# ==========================================
# 📊 PAGE 5: MACHINE HEALTH & OEE
# ==========================================
def render_machine_health():
    st.title("🔧 Machine Health & OEE (Mechanic Agent)")
    if df.empty: return st.warning("No data available.")
    
    # Machine Ranking
    st.subheader("Machine Operating Ranking")
    latest_oee = df.groupby('Assigned_Facility')['Machine_OEE_Pct'].mean().sort_values().reset_index()
    fig_bar = px.bar(latest_oee, x='Machine_OEE_Pct', y='Assigned_Facility', orientation='h',
                     title="Average OEE by Facility (Lower is worse)", color='Machine_OEE_Pct',
                     color_continuous_scale="RdYlGn")
    st.plotly_chart(fig_bar, use_container_width=True)
    
    st.subheader("Sensor Telemetry")
    fac = st.selectbox("Select Facility for Telemetry", df['Assigned_Facility'].unique())
    fac_df = df[df['Assigned_Facility'] == fac].tail(100)
    
    fig_ttf = px.line(fac_df, x='Timestamp', y='Predicted_Time_To_Failure_Hrs', 
                      title="Predicted Time To Failure (hrs)")
    fig_ttf.add_hline(y=50, line_dash="dash", line_color="red", annotation_text="Warning Threshold")
    st.plotly_chart(fig_ttf, use_container_width=True)
    
    c1, c2 = st.columns(2)
    with c1:
        fig_temp = px.line(fac_df, x='Timestamp', y='Machine_Temperature_C', title="Temperature (°C)")
        st.plotly_chart(fig_temp, use_container_width=True)
    with c2:
        fig_vib = px.line(fac_df, x='Timestamp', y='Machine_Vibration_Hz', title="Vibration (Hz)")
        st.plotly_chart(fig_vib, use_container_width=True)

# ==========================================
# 📊 PAGE 6: INVENTORY & PROCUREMENT
# ==========================================
def render_inventory():
    st.title("📦 Inventory & Procurement (Buyer Agent)")
    if df.empty: return st.warning("No data available.")
    
    st.subheader("Current Inventory Levels")
    
    latest_inv = df.groupby('Assigned_Facility').last().reset_index()
    
    fig_inv = px.bar(latest_inv, x='Assigned_Facility', y=['Raw_Material_Inventory_Units', 'Inventory_Threshold'],
                     barmode='overlay', title="Inventory vs Threshold")
    st.plotly_chart(fig_inv, use_container_width=True)
    
    st.subheader("Procurement Log")
    procurement_events = df[df['Procurement_Action'] != 'None']
    if not procurement_events.empty:
        disp_cols = ['Timestamp', 'Assigned_Facility', 'Procurement_Action', 'Live_Supplier_Quote_USD', 'Inventory_Threshold']
        st.dataframe(procurement_events[disp_cols].tail(10), use_container_width=True)
    else:
        st.success("No emergency auto-orders triggered recently.")

# ==========================================
# 📊 PAGE 7: CARBON & ENERGY DASHBOARD
# ==========================================
def render_carbon_dashboard():
    st.title("🌱 Carbon & Energy Dashboard (Environmentalist Agent)")
    if df.empty: return st.warning("No data available.")
    
    df['Hour'] = df['Timestamp'].dt.hour
    df['DayOfWeek'] = df['Timestamp'].dt.day_name()
    
    c1, c2, c3 = st.columns(3)
    total_carbon = df['Carbon_Emissions_kg'].sum()
    total_penalty = df['Carbon_Cost_Penalty_USD'].sum()
    peak_penalty = df[df['Grid_Pricing_Period'] == 'Peak']['Carbon_Cost_Penalty_USD'].sum()
    
    c1.metric("Total Emissions", f"{total_carbon:,.0f} kg")
    c2.metric("Total Carbon Penalty", f"${total_penalty:,.0f}")
    c3.metric("Peak Hour Penalty", f"${peak_penalty:,.0f}")
    
    st.subheader("Energy Consumption Heatmap")
    heatmap_data = df.groupby(['DayOfWeek', 'Hour'])['Energy_Consumed_kWh'].mean().reset_index()
    fig_heat = px.density_heatmap(heatmap_data, x='Hour', y='DayOfWeek', z='Energy_Consumed_kWh',
                                  title="Average Energy Usage (kWh)", color_continuous_scale="Viridis",
                                  category_orders={"DayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]})
    
    # Highlight 14:00 - 20:00 Peak (assuming these are peak hours from plan)
    fig_heat.add_vrect(x0=14, x1=20, fillcolor="red", opacity=0.2, line_width=0, annotation_text="Peak Pricing")
    st.plotly_chart(fig_heat, use_container_width=True)
    
    if peak_penalty > 0:
        st.info(f"💡 **Optimization Suggestion:** Shifting 30% of jobs from Peak to Off-peak could save approximately **${(peak_penalty*0.3):,.0f}** in carbon penalties.")

# ==========================================
# 📊 PAGE 8: NATURAL LANGUAGE INTERFACE
# ==========================================
def render_nl_interface():
    st.title("💬 Natural Language Interface")
    st.markdown("Ask the Agentic System questions about the current production state.")
    
    query = st.text_input("Enter your query:", placeholder="e.g. Why is the order delayed? What happens if Line 2 fails?")
    
    if query:
        q_lower = query.lower()
        st.markdown("### Agent Response")
        
        # Rule-based routing
        if "delay" in q_lower or "late" in q_lower:
            agent = "Orchestrator"
            conf = 92.5
            delayed_orders = df[df['Schedule_Status'] == 'Delayed']
            ans = f"There are currently {len(delayed_orders)} delayed events in the history. Most are due to capacity overflows or machine maintenance routing."
        elif "fail" in q_lower or "machine" in q_lower or "line" in q_lower:
            agent = "Mechanic"
            conf = 88.0
            worst_ttf = df['Predicted_Time_To_Failure_Hrs'].min()
            ans = f"If a line fails, production halts for that facility. Currently, the most at-risk machine has a Predicted Time To Failure of {worst_ttf:.1f} hours."
        elif "carbon" in q_lower or "energy" in q_lower:
            agent = "Environmentalist"
            conf = 95.5
            peak_penalty = df[df['Grid_Pricing_Period'] == 'Peak']['Carbon_Cost_Penalty_USD'].sum()
            ans = f"We are tracking carbon penalties closely. Peak hour operations have accumulated ${peak_penalty:,.0f} in penalties so far."
        elif "inventory" in q_lower or "stock" in q_lower:
            agent = "Buyer"
            conf = 99.0
            min_inv = df['Raw_Material_Inventory_Units'].min()
            ans = f"Inventory thresholds are monitored. The lowest recorded stock is {min_inv:,} units. Auto-ordering APIs are active."
        elif "demand" in q_lower or "spike" in q_lower:
            agent = "Forecaster"
            conf = 91.2
            ans = "I continuously monitor demand vs actuals. Deviation spikes >30% are flagged automatically on the Demand Intelligence dashboard."
        else:
            agent = "Orchestrator"
            conf = 75.0
            ans = "I'm monitoring the global system. All primary facilities are online. Specify a query about delays, machines, inventory, or carbon."
            
        with st.container():
            st.markdown(f"""
            <div style="border-left: 4px solid {COLORS['info']}; padding-left: 15px; margin: 10px 0; background-color: #1E1E1E; padding: 15px; border-radius: 0 5px 5px 0;">
                <p style="font-size: 18px; margin-bottom: 5px;">{ans}</p>
                <div style="font-size: 13px; color: #aaa;">
                    <b>Agent Responsible:</b> {agent} &bull; <b>Confidence:</b> {conf}%
                </div>
            </div>
            """, unsafe_allow_html=True)

# ==========================================
# 🔄 MAIN LOOP & NAVIGATION
# ==========================================
def main():
    # Sidebar
    st.sidebar.title("Navigation")
    
    pages = {
        "📊 Command Center": render_command_center,
        "📈 Demand Intelligence": render_demand_intelligence,
        "🗓️ Production Schedule": render_production_schedule,
        "🧬 Digital Twin": render_digital_twin,
        "🔧 Machine Health": render_machine_health,
        "📦 Inventory & Procurement": render_inventory,
        "🌱 Carbon & Energy Dashboard": render_carbon_dashboard,
        "💬 NLP Interface": render_nl_interface
    }
    
    selection = st.sidebar.radio("Go to", list(pages.keys()))
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("⏱️ Simulation Controls")
    
    st.sidebar.markdown(f"**Current Time:**\n{current_time.strftime('%Y-%m-%d %H:%00')}")
    st.sidebar.markdown(f"**Events Processed:** {st.session_state.time_cursor} / {len(df_full)}")
    
    step_size = st.sidebar.slider("Simulation Speed (Events per tick)", 1, 50, 10)
    
    col1, col2 = st.sidebar.columns(2)
    if col1.button("⏭️ Next Tick"):
        advance_time(step_size)
        st.rerun()
    if col2.button("🔄 Reset"):
        st.session_state.time_cursor = min(100, len(df_full))
        st.session_state.agent_log = st.session_state.agent_log.iloc[0:0] # clear
        st.rerun()

    # Render selected page
    pages[selection]()

if __name__ == "__main__":
    main()
