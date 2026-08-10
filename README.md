# AI Chronicle — niche AI news archive

Static website + daily free ingestion from public RSS / company blogs.

## Structure

```
ai-newsletter/
├── web/                 ← website (open index.html via local server or host on Netlify)
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   └── data.json        ← updated daily by GitHub Actions
├── ingestion/           ← pipeline
│   ├── ingest_rss.py
│   ├── scrape_anthropic.py
│   ├── fetch_bodies.py
│   ├── export_for_web.py
│   ├── feeds.yaml
│   └── requirements.txt
└── .github/workflows/
    └── daily-ingest.yml ← runs every day at 07:00 IST
```

## One-time setup (GitHub Actions — fully automatic)

### 1. Create a GitHub repo

1. Go to https://github.com/new  
2. Name it e.g. `ai-newsletter` (public or private)  
3. **Do not** add README if you will push this folder

### 2. Push this project

On your Windows PC (PowerShell), from the folder that contains `web` and `ingestion`:

```powershell
cd C:\Users\vaibh\Downloads\ai-newsletter

git init
git add .
git commit -m "Initial AI Chronicle site + ingestion pipeline"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/ai-newsletter.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

### 3. Enable Actions

- Open the repo on GitHub → **Actions** tab  
- If asked, enable workflows  
- Open **Daily AI News Ingest** → **Run workflow** (manual test)

After a successful run, `web/data.json` will be updated and committed automatically every day at **07:00 IST**.

### 4. Host the website (free)

**Netlify (easiest)**  
1. https://app.netlify.com → Add new site → Import from Git  
2. Select your repo  
3. Publish directory: `web`  
4. Deploy  

You get a URL like `https://random-name.netlify.app`.  
Optional: add a custom domain.

**GitHub Pages**  
Settings → Pages → Source: Deploy from branch `main` / folder `/web`  
(or use a simple static deploy action).

Every morning after the workflow runs, Netlify/GitHub Pages will pick up the new `data.json` and the site shows fresh news.

## Manual run (local)

```powershell
cd C:\Users\vaibh\Downloads\ai-newsletter\ingestion
pip install -r requirements.txt
python ingest_rss.py --days 7
python scrape_anthropic.py
python fetch_bodies.py --source Anthropic --limit 20
python export_for_web.py --limit 150
```

Then refresh the site (or re-deploy `web/`).

## Local preview

```powershell
cd C:\Users\vaibh\Downloads\ai-newsletter\web
python -m http.server 8765
```

Open http://127.0.0.1:8765/

## Cost

- RSS + public pages: **free**  
- GitHub Actions free tier: enough for 1 daily job  
- Netlify / GitHub Pages free tier: enough for this site  
- No paid news API required  

## Notes

- Dates on the site use **IST (GMT+5:30)**  
- Milestones (history, lawsuits, incidents, jobs, culture) are curated in `data.json` and kept across exports  
- Anthropic has no official RSS → scraper  
- Some sites block full-body fetch (e.g. OpenAI 403); titles + RSS summaries still appear  
- Be polite: the scripts already use delays and a clear User-Agent  
