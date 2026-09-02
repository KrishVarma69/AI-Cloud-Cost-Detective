## AI Cloud Cost Detective (AWS) - Architecture

```
                              ┌──────────────┐
                              │     USER     │
                              └──────┬───────┘
                                     │
                                     ▼
                           ┌───────────────────┐
                           │  REACT FRONTEND   │
                           └────────┬──────────┘
                                    :
                                    : Login / Signup
                                    ▼
                           ┌───────────────────┐
                           │  PYTHON BACKEND   │
                           │    (FastAPI)      │
                           │                   │
                           │  · Custom JWT Auth│
                           └───┬───────┬───┬───┘
                               :       :   :
                ┌──────────────┘       :   └──────────────┐
                :                      :                  :
                ▼                      ▼                  ▼
         ┌─────────────┐     ┌──────────────┐    ┌──────────────┐
         │   AWS CLI   │     │   FASTAPI    │    │   OPENAI     │
         │             │     │  WEBSOCKET   │    │    API       │
         │ tag:GetRes. │     │  (Progress)  │    │              │
         │ ce:GetCost  │     └──────┬───────┘    │ Cost Analysis│
         └──────┬──────┘            :            └──────┬───────┘
                :                   : Live updates      :
                ▼                   ▼                   :
         ┌─────────────┐   ┌───────────────┐            :
         │     AWS     │   │    REACT      │            :
         │  (Account / │   │  (Progress    │            :
         │   Region)   │   │   Tracker)    │            :
         └─────────────┘   └───────────────┘            :
                                                        ▼
                                                 ┌──────────────┐
                                                 │  AMAZON RDS  │
                                                 │  POSTGRESQL  │
                                                 │              │
                                                 │ · users      │
                                                 │ · analyses   │
                                                 └──────┬───────┘
                                                        :
                                                        : Stored results
                                                        ▼
                                                 ┌───────────────┐
                                                 │    REACT      │
                                                 │ (Final Report │
                                                 │  + Suggestions│
                                                 │  + Fixes)     │
                                                 └───────────────┘
```

## Components

| Component | Responsibility |
|---|---|
| **React Frontend** | Auth forms, region/resource-group picker, live progress tracker, analysis report, history |
| **FastAPI Backend** | JWT auth, orchestration of scan → analyze → store, WebSocket progress broadcast |
| **AWS CLI layer** (`aws_scanner.py`) | `aws resourcegroupstaggingapi get-resources` for inventory; `aws ce get-cost-and-usage` + `aws ce get-rightsizing-recommendation` for real spend and rightsizing hints; service `describe`/`list` calls for idle-resource detection |
| **AI Analyzer** (`ai_analyzer.py`) | Builds the prompt from resources + cost data, calls OpenAI `gpt-4o`, returns structured issues, savings, and AWS CLI fix commands |
| **RDS PostgreSQL** (`db.py`) | `users` and `analyses` tables; connection string in `DATABASE_URL` |
| **FastAPI WebSocket** | Streams stage-by-stage progress to the frontend during an analysis run |
