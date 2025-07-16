from flask import Flask, request, jsonify, send_file
from transformers import pipeline
from bs4 import BeautifulSoup
import requests
import re
import uuid
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Allows access from the Chrome extension

# Load model
pipe = pipeline("text-classification", model="climatebert/environmental-claims")

# Buzzwords for greenwashing suspicion
buzzwords = [
    "green", "eco", "net-zero", "carbon neutral", "sustainable", "planet",
    "responsible", "environmentally friendly", "clean energy", "climate-friendly", 
    "bio", "ethical", "natural"
]

# SERPAPI Key (replace or use env variable)
SERPAPI_KEY = "a6857984fb04fb5373d77ce30cb01e637aa5360c76f36e530059119a9ebafa15"

def extract_clean_text(url):
    try:
        response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "header", "footer", "nav", "aside"]):
            tag.decompose()

        content = " ".join(tag.get_text(separator=" ", strip=True) for tag in soup.find_all(["p", "li", "article", "section", "div"]))
        return re.sub(r"\s+", " ", content).strip()
    except Exception as e:
        return f"❌ Error: {e}"

def analyze_text(raw_text):
    sentences = re.split(r'(?<=[.?!])\s+', raw_text)
    sentences = list(dict.fromkeys(sentences))  # Deduplicate

    analyzed = []
    top_suspects = []

    for sentence in sentences:
        if len(sentence.split()) < 5:
            continue

        result = pipe(sentence)[0]
        score = result["score"] * 100
        label = result["label"]

        if label == "LABEL_1":
            tag = f"✅ Genuine Claim ({score:.1f}%)"
        elif any(word in sentence.lower() for word in buzzwords):
            tag = f"⚠️ Likely Greenwashing ({score:.1f}% sure it's *not* a claim)"
            top_suspects.append((sentence, score))
        else:
            tag = "🤔 Unclear"

        analyzed.append(f"{sentence} → {tag}")

    top_suspects = sorted(set(top_suspects), key=lambda x: -x[1])[:5]

    result_md = "🔎 Full Analysis:\n" + "\n\n".join(f"- {line}" for line in analyzed)
    if top_suspects:
        result_md += "\n\n⚠️ Top 5 Likely Greenwashing Statements:\n"
        for s, _ in top_suspects:
            result_md += f"- {s.strip()}\n"

    # Save report
    filename = f"greenwashing_report_{uuid.uuid4().hex[:8]}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(result_md)

    return result_md, filename

def fact_check(claim):
    try:
        params = {
            "engine": "google",
            "q": claim,
            "api_key": SERPAPI_KEY,
            "num": 5
        }
        response = requests.get("https://serpapi.com/search", params=params)
        data = response.json()

        if "error" in data:
            return f"❌ SerpAPI Error: {data['error']}"

        results = data.get("organic_results", [])[:3]
        if not results:
            return "⚠️ No supporting sources found."

        output = []
        for res in results:
            title = res.get("title", "No Title")
            snippet = res.get("snippet", "No Snippet")
            link = res.get("link", "")
            output.append({
                "title": title,
                "snippet": snippet,
                "link": link
            })
        return output
    except Exception as e:
        return f"❌ Error during fact check: {e}"

# Endpoint: Analyze URL and (optionally) fact-check
@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    url = data.get("url")
    claim = data.get("claim", "")

    raw_text = extract_clean_text(url)
    if raw_text.startswith("❌"):
        return jsonify({"error": raw_text}), 400

    analysis_text, filename = analyze_text(raw_text)
    fact_result = fact_check(claim) if claim else None

    return jsonify({
        "analysis": analysis_text,
        "report_file": filename,
        "fact_check": fact_result
    })

# Endpoint: Download report
@app.route("/download/<filename>")
def download(filename):
    return send_file(filename, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
