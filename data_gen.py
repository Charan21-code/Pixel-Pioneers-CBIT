import pandas as pd
import numpy as np
from datetime import timedelta

# 1. Configuration & Constants
NUM_ROWS = 10000
START_DATE = '2024-01-01'

PRODUCTS = [
    'Galaxy S Smartphone', 'Galaxy A Smartphone', 'Galaxy Tab', 
    'Neo QLED TV', 'Bespoke Refrigerator', 'EcoBubble Washing Machine'
]

REGIONS = [
    'India', 'China', 'USA', 'Japan', 'Korea', 
    'Malaysia (SEA)', 'Middle East', 'Australia/NZ', 'Europe', 'Africa'
]

# Realistic Samsung-style manufacturing hubs
FACILITIES = [
    'Noida Plant (India) - Primary',
    'Thai Nguyen (Vietnam) - Primary',
    'Gumi (Korea) - Primary',
    'Queretaro (Mexico) - Partner',
    'Foxconn (Taiwan) - Partner Overflow'
]

print("Generating synthetic Samsung production data...")

# 2. Base DataFrame & Time Series
# Generating a schedule log entry every ~2 hours
timestamps = pd.date_range(start=START_DATE, periods=NUM_ROWS, freq='2h')
df = pd.DataFrame({'Timestamp': timestamps})

# Basic Assignments
df['Order_ID'] = ['ORD-' + str(100000 + i) for i in range(NUM_ROWS)]
df['Product_Category'] = np.random.choice(PRODUCTS, NUM_ROWS, p=[0.3, 0.2, 0.15, 0.15, 0.1, 0.1])
df['Region'] = np.random.choice(REGIONS, NUM_ROWS)
df['Assigned_Facility'] = np.random.choice(FACILITIES, NUM_ROWS, p=[0.3, 0.3, 0.2, 0.1, 0.1])
df['Production_Line'] = np.random.choice(['Line 1 (High Speed)', 'Line 2 (Standard)', 'Line 3 (Heavy Duty)'], NUM_ROWS)

# 3. Demand Intelligence (The Forecaster)
# We use a sine wave over the year to simulate seasonality (e.g., higher demand in Q4 for holidays)
day_of_year = df['Timestamp'].dt.dayofyear
seasonality_multiplier = 1 + 0.3 * np.sin(2 * np.pi * day_of_year / 365)

base_demand = np.where(df['Product_Category'].str.contains('Smartphone'), 5000, 1000)
df['Forecasted_Demand'] = (base_demand * seasonality_multiplier + np.random.normal(0, 200, NUM_ROWS)).astype(int)

# Actual demand mostly matches forecast, but we inject sudden 50% spikes 5% of the time to test the AI
df['Actual_Order_Qty'] = df['Forecasted_Demand'].copy()
spike_indices = np.random.choice(df.index, size=int(NUM_ROWS * 0.05), replace=False)
df.loc[spike_indices, 'Actual_Order_Qty'] = (df.loc[spike_indices, 'Actual_Order_Qty'] * 1.5).astype(int)

# 4. Scheduling & Workforce (The Orchestrator)
df['Workforce_Required'] = np.where(df['Product_Category'].str.contains('Smartphone'), 150, 80)
# Most of the time workforce is met, occasionally there is a 10-20% shortage (absenteeism)
shortage_factor = np.random.choice([1.0, 0.9, 0.8], NUM_ROWS, p=[0.85, 0.1, 0.05])
df['Workforce_Deployed'] = (df['Workforce_Required'] * shortage_factor).astype(int)

df['Schedule_Status'] = np.where(df['Workforce_Deployed'] < df['Workforce_Required'], 'Delayed', 'On-Time')
df.loc[spike_indices, 'Schedule_Status'] = 'Rerouted' # Spikes cause rerouting

# Human in the loop overrides (random 2% of the time)
df['Operator_Override_Flag'] = np.random.choice([0, 1], NUM_ROWS, p=[0.98, 0.02])

# 5. Predictive Maintenance (The Mechanic)
# Base healthy state
df['Machine_Temperature_C'] = np.random.normal(75, 2, NUM_ROWS)
df['Machine_Vibration_Hz'] = np.random.normal(50, 3, NUM_ROWS)
df['Predicted_Time_To_Failure_Hrs'] = np.random.uniform(300, 500, NUM_ROWS)
df['Machine_OEE_Pct'] = np.random.uniform(88, 98, NUM_ROWS)

# Inject Realistic Degradation Curves (Anomalies)
# Every ~800 rows, a machine starts failing over a 12-row window (24 hours)
for start_idx in range(500, NUM_ROWS, 800):
    end_idx = min(start_idx + 12, NUM_ROWS)
    window_size = end_idx - start_idx
    if window_size > 0:
        # Temp and vibration rise linearly
        df.loc[start_idx:end_idx-1, 'Machine_Temperature_C'] = np.linspace(75, 95, window_size) + np.random.normal(0, 1, window_size)
        df.loc[start_idx:end_idx-1, 'Machine_Vibration_Hz'] = np.linspace(50, 85, window_size) + np.random.normal(0, 1, window_size)
        # Time to failure drops to near zero
        df.loc[start_idx:end_idx-1, 'Predicted_Time_To_Failure_Hrs'] = np.linspace(24, 1, window_size)
        # OEE drops
        df.loc[start_idx:end_idx-1, 'Machine_OEE_Pct'] = np.linspace(90, 65, window_size)
        # Mark schedule as 'Maintenance Reroute' at the critical point
        df.loc[end_idx-2:end_idx, 'Schedule_Status'] = 'Maintenance Reroute'

# 6. Inventory & Agentic Procurement (The Buyer)
# We simulate a running inventory that depletes based on actual order quantity
inventory_state = {prod: 100000 for prod in PRODUCTS} # Start with 100k components each
inv_logs = []
proc_actions = []
quotes = []

for index, row in df.iterrows():
    prod = row['Product_Category']
    qty = row['Actual_Order_Qty']
    
    # Deplete inventory (assume 1 unit of product takes 1 unit of a core component batch)
    inventory_state[prod] -= qty
    
    threshold = 20000
    if inventory_state[prod] <= threshold:
        inv_logs.append(inventory_state[prod])
        proc_actions.append('Auto-Ordered via API')
        # Simulate agent negotiating between $5.00 and $5.50 per component batch
        quotes.append(round(np.random.uniform(5.00, 5.50), 2))
        # Restock inventory
        inventory_state[prod] += 150000 
    else:
        inv_logs.append(inventory_state[prod])
        proc_actions.append('None')
        quotes.append(0.0)

df['Raw_Material_Inventory_Units'] = inv_logs
df['Inventory_Threshold'] = 20000
df['Procurement_Action'] = proc_actions
df['Live_Supplier_Quote_USD'] = quotes

# 7. Carbon & Sustainability (The Environmentalist)
# If the hour is between 14:00 (2 PM) and 20:00 (8 PM), it's peak grid pricing
df['Hour'] = df['Timestamp'].dt.hour
df['Grid_Pricing_Period'] = np.where((df['Hour'] >= 14) & (df['Hour'] <= 20), 'Peak', 'Off-Peak')

# Energy consumed relates to product type and actual quantity
df['Energy_Consumed_kWh'] = (df['Actual_Order_Qty'] * np.where(df['Product_Category'].str.contains('Refrigerator|Washing'), 2.5, 0.5)).astype(int)

# Carbon footprint (assume 0.4 kg CO2 per kWh on average)
df['Carbon_Emissions_kg'] = df['Energy_Consumed_kWh'] * 0.4

# Apply financial penalty for running heavy production during peak hours
df['Carbon_Cost_Penalty_USD'] = np.where(df['Grid_Pricing_Period'] == 'Peak', df['Energy_Consumed_kWh'] * 0.15, 0).round(2)
df.drop('Hour', axis=1, inplace=True) # Clean up temporary column

# 8. Save to CSV
output_filename = 'samsung_production_logs.csv'
df.to_csv(output_filename, index=False)
print(f"Success! Generated {NUM_ROWS} rows of data saved to '{output_filename}'.")