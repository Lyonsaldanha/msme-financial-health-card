# MSME Financial Health Card — Frontend Context

## Stack
- **Framework:** Streamlit (Python native)
- **Auth:** Hardcoded for prototype (session-based if time permits)
- **Customers:** 5-6 mock customers for prototype

---

## UI Flow

```
Login Page
    ↓
Customer Form (manual entry)
    ↓
Async Backend Call (ETL → Analytics → AI Engine)
    ↓
Financial Health Card (Visual)
```

---

## Page 1: Login
- Username + Password (hardcoded for prototype)
- Session state management via Streamlit `st.session_state`
- On success → redirect to Customer Form

---

## Page 2: Customer Form
- Manual entry fields:
  - Business Name
  - GST Number
  - UPI ID
  - EPFO ID
  - Bank Account (AA reference)
- Submit button → triggers async backend call

---

## Page 3: Async Backend Call (Loading State)
- Streamlit spinner with progressive status messages:
  - "Fetching GST data..."
  - "Fetching UPI data..."
  - "Computing ratios..."
  - "Generating report..."
- Progress bar reflecting ETL → Analytics → AI Engine stages

---

## Page 4: Financial Health Card

### Layout
```
┌─────────────────────────────────────┐
│ Customer Name | GST No | Sector     │
│ Composite Score: 72/100 [GAUGE]     │
├──────────┬──────────┬───────────────┤
│ GST      │ UPI      │ AA    │ EPFO  │
│ Score    │ Score    │ Score │ Score │
│ 68/100   │ 75/100   │ 80    │ 65    │
├──────────┴──────────┴───────────────┤
│ [Charts: Bar, Line, Gauge, Table]   │
├─────────────────────────────────────┤
│ AI Narrative (key findings)         │
├─────────────────────────────────────┤
│ Red Flags        | Green Flags      │
├─────────────────────────────────────┤
│ [Download PDF Report]               │
└─────────────────────────────────────┘
```

### Components
- **Header:** Business name, GST number, sector
- **Composite Score:** Gauge chart (0–100)
- **Source Score Cards:** GST / UPI / AA / EPFO individual scores (4 columns)
- **Charts:** Matplotlib renders from LLM chart config JSON
  - Bar (GST monthly turnover, employee count)
  - Line (revenue trend, cash balance)
  - Gauge (DSCR, CV)
  - Table (cross-validation reconciliation)
  - Pie (debt composition, revenue concentration)
- **AI Narrative:** Key findings from LLM (markdown rendered)
- **Flags:**
  - Red Flags (risk indicators)
  - Green Flags (strength indicators)
- **Download PDF:** Export full report

---

## Open Design Decision
- **Credit Action Buttons:** TBD based on workflow
  - If officer decides independently → Add Recommend / Approve / Reject buttons
  - If maker/checker workflow → Card is read-only, feeds into approval system
  - *To be confirmed with stakeholder*

---

## Key Design Principles
- Officer sees progressive loading (not blank screen during async call)
- Health Card is self-contained (no need to navigate away)
- Every chart and narrative is traceable to source data
- PDF export mirrors exactly what officer sees on screen
