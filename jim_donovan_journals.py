import requests, json,os
from dotenv import load_dotenv
load_dotenv()
import re
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import sqlite3
from groq import Groq
from langchain_groq import ChatGroq
import pandas as pd


def fetch_articles():
    api_key=os.getenv("NEWS_API_KEY")
    url="https://newsapi.org/v2/everything"
    params={
        "q":"economy OR inflation OR IPO OR earnings OR opinion",
        "language":"en",
        "page_size":20,
        "apikey":api_key
    }
    res= requests.get(url,params=params)
    return res.json().get("articles",[])

def classify_article(title,description):
    macro_keywords=["inflation", "interest rates", "GDP", "monetary", "fiscal"]
    company_keywords = ["IPO", "earnings", "merger", "company", "revenue"]
    oped_keywords = ["opinion", "editorial", "analysis", "column"]

    text=f"{title} {description}".lower()
    if any(word in text for word in macro_keywords):
        return "Macro Economics"
    elif any(word in text for word in company_keywords):
        return "Company / Industry"
    elif any(word in text for word in oped_keywords):
        return "Op-Ed"
    else:
        return "Other"

DB_PATH=r"database/article.db"
os.makedirs("database",exist_ok=True)
def init_db():
    conn= sqlite3.connect(DB_PATH)
    cur=conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS read_articles (
                title TEXT,
                url TEXT,
                category TEXT,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
        """)
    conn.commit()
    conn.close()

def article_exists(url):
    conn=sqlite3.connect(DB_PATH)
    cur=conn.cursor()
    cur.execute("SELECT 1 FROM read_articles WHERE url = ?", (url,))
    exists=cur.fetchone() is not None
    conn.close()
    return exists

def log_article(title, url, category):
    conn=sqlite3.connect(DB_PATH)
    cur=conn.cursor()
    cur.execute("INSERT INTO read_articles (title, url, category) VALUES (?,?,?)", (title, url, category))
    conn.commit()
    conn.close()

client=Groq(api_key=os.getenv("GROQ_API_KEY"))
def llm_score(title, description,category):
    prompt = f"""
    You are an expert content filter.
    Rate from 1 to 10 how relevant this article is to the category: {category}.
    Respond ONLY with a number between 1 and 10.

    Title: {title}
    Description: {description}
    """

    response = client.chat.completions.create(
        model="qwen/qwen3-32b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    output=response.choices[0].message.content.strip()
    score_match = re.search(r'\b([1-9]|10)\b', output)
    if score_match:
        return int(score_match.group())
    else:
        print(f" Unexpected response: {output}")
        return 0
    

def get_top_articles(articles):
  if not articles:
    return []
  df = pd.DataFrame(articles)

  best_articles = (
      df.sort_values("score", ascending=False)
        .groupby("category")
        .head(1)
        .reset_index(drop=True)
  )
  return best_articles.to_dict(orient="records")
    # return int(score_match.group()) if score_match else 0



def get_top_articles(articles):
  if not articles:
    return []
  df = pd.DataFrame(articles)

  best_articles = (
      df.sort_values("score", ascending=False)
        .groupby("category")
        .head(1)
        .reset_index(drop=True)
  )
  return best_articles.to_dict(orient="records")

def send_email(top_articles):
    sender = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASS")
    receiver = sender  # you can also change this to another recipient

    # Build email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "📰 Your Daily 3 Reads"
    msg["From"] = sender
    msg["To"] = receiver

    html_content = "<h3>Here are your 3 articles for today:</h3><ul>"
    for a in top_articles:
        html_content += f"<li><b>{a['category']}</b>: <a href='{a['url']}'>{a['title']}</a></li>"
    html_content += "</ul><br><p>Enjoy your reading! ☕</p>"

    msg.attach(MIMEText(html_content, "html"))

    # Connect securely to Gmail SMTP (SSL port 465)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.send_message(msg)
        print("✅ Email sent successfully!")

def main():
    init_db()
    all_articles=[]
    
    articles=fetch_articles()
    new_articles = [a for a in articles if not article_exists(a.get("url", ""))]
    print(f"🆕 Found {len(new_articles)} new articles to process...")
    

    for article in new_articles:
        title=article.get("title","")
        description=article.get("description","")
        source=article.get("source",{}).get("name","")
        url=article.get("url","")

        category= classify_article(title, description )
        if category != "Other":
            score = llm_score(title, description, category)
            all_articles.append({
                "title": title,
                "description":description,
                "source":source,
                "url":url,
                "category":category,
                "score": score
            })
    top_articles=get_top_articles(all_articles)
    for a in top_articles:
        log_article(a["title"], a["url"],a["category"])

    send_email(top_articles)
    print("✅ Email sent with 3 top articles!")
