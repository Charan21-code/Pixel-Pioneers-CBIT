# Hackathon Judge Q&A Prep: Agentic Production Planning System

This document contains answers to the 4 most critical questions judges will ask regarding the technical viability and business value of the project.

---

## 1. What problem is our product even solving?

**The Core Problem: The Latency of Human Coordination during Disruption.**
Currently, manufacturing operates in silos using rigid, static schedules. When a disruption occurs—a machine breaks down, a supplier delays a raw material, or demand suddenly spikes—the factory goes into chaos. 
*   The mechanic logs the error.
*   The planner recalculates the spreadsheet.
*   The procurement officer scrambles to buy parts.
*   Finance must approve the budget.

This manual coordination takes hours or days, causing a massive "butterfly effect" of downtime, delayed shipments, and excess costs.

**Our Solution:** 
We solve the **speed of alignment**. By assigning an AI agent to represent each department, our system actively monitors live data and cross-communicates instantly. If a machine fails, our system automatically recalculates the schedule, requests a replacement part, and queues the invoice for human approval—all in milliseconds. We turn a reactive factory into a proactive, self-healing network.

---

## 2. How different and optimized is our project? (How do we use LLMs efficiently?)

**The Difference:**
Most companies just slap a "chatbot" on their product and call it AI. That is highly inefficient for production environments because LLMs are bad at doing raw math and prone to hallucinating. 

**Our Efficient Use of LLM Technology:**
1.  **Orchestration over Calculation:** We don't use LLMs to calculate math. We use standard deterministic Python logic (Pandas/NumPy) for the heavy data crunching. We solely use LLMs as the **cognitive brain** to interpret the data, recognize context, and make strategic decisions (e.g., "This machine failure means we will miss our SLA, so we must switch to a faster, more expensive supplier").
2.  **Multi-Agent Specialization:** Instead of sending massive, confusing prompts to one AI, we split the cognitive load. The Environmental Agent only gets carbon data. The Finance Agent only gets budget data. This drastically reduces the context window (token count), resulting in insanely fast generation speeds and near-zero hallucinations.
3.  **Local & Quantized Models:** By relying on frameworks like Ollama, we aren't relying on expensive OpenAI API calls. We are running local AI.

---

## 3. What are the minimum specifications required to run this efficiently?

Because we heavily optimized our system to run on local, quantized LLMs (like Llama-3 8B or Phi-3 compressed to 4-bit), the hardware overhead is surprisingly low compared to massive cloud AI setups.

*   **Central Orchestrator Server (On-Premise):**
    *   **CPU:** Modern 8 to 16-core processor (Intel i7/i9 or AMD Ryzen).
    *   **RAM:** 32GB to 64GB (Crucial for holding the LLM weights in memory and processing pandas data frames).
    *   **GPU:** A single consumer-grade or entry-enterprise GPU (e.g., Nvidia RTX 3090, 4090, or A5000 with 24GB VRAM) is more than enough to inference our localized agents smoothly.
*   **Factory Floor Sensors (Edge Layer):**
    *   Standard Industrial IoT specifications (e.g., Raspberry Pi 4s or basic PLCs) purely meant to push telemetry data to the central database; no heavy ML runs on the edge.

---

## 4. How would you deploy this into the real world?

A real-world factory cannot afford to instantly rip out their multi-million dollar software, nor can they risk uploading their trade secrets to a public cloud API. 

**Our Deployment Strategy:**
1.  **Hybrid Cloud / On-Premise Architecture:** To guarantee absolute data privacy and comply with manufacturing security standards, the LLM inferences and database will be deployed entirely on bare-metal servers inside the factory's private network (Virtual Private Cloud). No proprietary data ever leaves the building.
2.  **API Integration Layer:** We don't replace their existing software on day one. Our system deploys as an "Intelligent Layer" sitting on top of their existing ERP (like SAP or Oracle) and MES (Manufacturing Execution Systems).
    *   **Ingestion:** We pull live data via REST APIs from their existing sensors and ERP databases.
    *   **Execution:** When our Orchestrator makes a decision, it pushes the updated schedule back into their ERP via API. 
3.  **Phased Rollout:** We would start deployed in **"Shadow Mode."** The AI makes recommendations but takes no actions. Once trust is established, we graduate to **HITL (Human-in-the-Loop)** where it needs one-click approval to act. Finally, standard operations are fully automated, leaving humans to only approve high-risk/high-cost anomalies.
