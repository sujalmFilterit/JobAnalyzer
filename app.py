import os
import pickle
import re
import threading
import webbrowser

import nltk 
import pandas as pd
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from nltk.stem import WordNetLemmatizer
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from thefuzz import process
from auth import router as auth_router, AuthMiddleware



nltk.download('wordnet', quiet=True)
nltk.download('omw-1.4', quiet=True)


DATABASE_URL = "sqlite:///./jobs_history.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ScanRecord(Base):
    __tablename__ = "scans"
    id = Column(Integer, primary_key=True, index=True)
    description_snippet = Column(String)
    result = Column(String)
    confidence = Column(String)

Base.metadata.create_all(bind=engine)


app = FastAPI()

app.include_router(auth_router)   # ← MongoDB auth routes
app.add_middleware(AuthMiddleware) # ← Route protection

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


if not os.path.exists("static"):
    os.makedirs("static")


app.mount("/static", StaticFiles(directory="static"), name="static")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

@app.get("/")
async def serve_index():
    index_path = os.path.join(BASE_DIR, "templates/index.html")
    if not os.path.exists(index_path):
        return {"error": f"Could not find index.html at {index_path}."}
    return FileResponse(index_path)

@app.get("/login")
async def serve_login():
    return FileResponse(os.path.join(BASE_DIR, "templates/login.html"))

@app.get("/signup")
async def serve_signup():
    return FileResponse(os.path.join(BASE_DIR, "templates/signup.html"))

@app.get("/analyze")
async def serve_analyze():
    return FileResponse(os.path.join(BASE_DIR, "templates/analyze.html"))


try:
    with open("model.pkl", "rb") as f:
        model = pickle.load(f)
    with open("tfidf.pkl", "rb") as f:
        tfidf = pickle.load(f)
except FileNotFoundError:
    print("WARNING: model.pkl or tfidf.pkl not found! Please run train_model.py first.")
    model = None
    tfidf = None


CSV_PATH = os.path.join(BASE_DIR, "list_of_companies.csv")

try:
 
    companies_df = pd.read_csv(CSV_PATH).fillna("N/A")
   
    valid_companies_list = companies_df['company_name'].astype(str).tolist()
    print(f" Successfully loaded {len(valid_companies_list)} companies from CSV.")
except FileNotFoundError:
    print(f"WARNING: File not found at {CSV_PATH}. Company validation will be skipped.")
    companies_df = pd.DataFrame() # Empty dataframe to prevent crash
    valid_companies_list = []
except KeyError:
    print("ERROR: Column 'company_name' not found! Check the exact column header in your CSV.")
    companies_df = pd.DataFrame()
    valid_companies_list = []

lemmatizer = WordNetLemmatizer()

def clean_text(text):
    text = text.lower()
    text = re.sub(r'[^a-z\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split()
    words = [lemmatizer.lemmatize(word) for word in words if word not in ENGLISH_STOP_WORDS]
    return " ".join(words)


@app.post("/predict")
async def predict(data: dict = Body(...)):
    if model is None or tfidf is None:
        return {"result": "System Offline", "confidence": "0.00%"}

    description = data.get("description", "")
    company_input = data.get("company", "") 
    
   
    cleaned = clean_text(description)
    vector = tfidf.transform([cleaned])
    prediction = model.predict(vector)[0]
    
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(vector)[0]
        confidence = f"{max(proba) * 100:.2f}%"
    else:
        confidence = "100.00%"
        
    ai_thinks_its_fake = bool(prediction == 1)

   
    company_exists = False
    matched_company = "None"
    company_info = {}
    
    if company_input and valid_companies_list:
        best_match, score = process.extractOne(company_input, valid_companies_list)
        if score >= 85:  
            company_exists = True
            matched_company = best_match
            
            
            row = companies_df[companies_df['company_name'] == best_match].iloc[0]
            
           
                                                         # Extract all the specific data points to send back to JS
            company_info = {
                "rating": str(row.get('Rating', 'N/A')),
                "reviews": str(row.get('Reviews', 'N/A')),
                "company_type": str(row.get('Company_type', 'N/A')),
                "location": str(row.get('Headquarter', 'N/A')),
                "age": str(row.get('Old', 'N/A')),
                "employees": str(row.get('No. of Employees', 'N/A')),
                "industry": str(row.get('industry', 'N/A'))
            }
           
    #  Override & Final Decision Logic 
    if ai_thinks_its_fake:
        final_result = "The job is likely suspicious or fraudulent based on the description provided."
    elif company_input and not company_exists:
        # The AI thought it was real, but the company doesn't exist! OVERRIDE.
        final_result = f"WARNING: AI marked this as real, but the company '{company_input}' could not be verified. Flagged as suspicious."
        confidence = "Override applied"
    else:
        final_result = "This job is to be real based on the given information."

    #  DATABASE LOGGING 
    db = SessionLocal()
    # Save just the first 50 chars of desc to save space
    record = ScanRecord(description_snippet=description[:50], result=final_result, confidence=confidence)
    db.add(record)
    db.commit()
    db.close()

    # Send all data back to the frontend (including company_info)
    return {
        "result": final_result, 
        "confidence": confidence,
        "company_exists": company_exists,
        "matched_company": matched_company,
        "company_info": company_info
    }

if __name__ == "__main__":
    import uvicorn
    
    # Open browser automatically after a short delay
    def open_browser():
        import time
        time.sleep(1.5)  # Wait for server to start
        webbrowser.open("http://127.0.0.1:8000")
    
    # Start browser opening in background thread
    threading.Thread(target=open_browser, daemon=True).start()
    
    print("Starting Fake Job Detector...")
    print("Opening http://127.0.0.1:8000 in your browser...")
    uvicorn.run(app, host="127.0.0.1", port=8000)