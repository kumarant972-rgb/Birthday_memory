# 🚀 Deployment guide — Render vs Vercel

## TL;DR

| | Render | Vercel |
|---|---|---|
| Persistent file storage (videos) | ✅ **Yes** (attach a Disk) | ❌ **No** (read-only FS, uploads lost) |
| Good for this app | ✅ **YES — recommended** | ⚠️ Only as a demo |
| Big file uploads (100s of MB) | ✅ Yes | ❌ Limited |

**This app stores uploaded birthday videos as files.** Because of that, **Render is
the right choice.** Vercel is serverless with no permanent file storage, so any video
someone uploads would disappear. Full steps for both are below.

---

## ✅ Option A — Render (recommended)

1. **Push the code to GitHub**
   ```bash
   cd birthday-memories
   git init
   git add .
   git commit -m "Birthday Memories"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```

2. **Create the service**
   - Go to [render.com](https://render.com) → **New +** → **Web Service**.
   - Connect your GitHub account and pick the repo.
   - Render reads `render.yaml` automatically (runtime, build, start command).

3. **Set the environment variables** (Environment tab):
   | Key | Value |
   |-----|-------|
   | `DATA_DIR` | `/opt/render/birthday-data` |
   | `ADMIN_ID` | your admin login (e.g. `admin`) |
   | `ADMIN_PASSWORD` | a strong password |

4. **Attach a persistent Disk** (this is the memory for all videos):
   - Service → **Disks** → **Add a Disk**.
   - Name: `birthday-data` · Mount Path: `/opt/render/birthday-data` · Size: e.g. 1 GB+.
   - ⚠️ The mount path MUST match `DATA_DIR` exactly.

5. **Deploy.** Wait for "Live", open the URL, then log in with your admin ID and
   change the password from the Admin Panel.

> On Render's free tier the service sleeps when idle; the first request after a pause
> takes a few seconds. The Disk keeps all files safe through restarts and redeploys.

---

## ⚠️ Option B — Vercel (demo only — uploads will NOT persist)

Use this only to show the site working. Videos/logins stored as files are wiped on
every deploy and between runs, because Vercel has no persistent storage.

1. Push the code to GitHub (same `git` steps as above).
2. Go to [vercel.com](https://vercel.com) → **Add New → Project** → import the repo.
3. Framework stays **Other**; the included `vercel.json` handles the build.
4. Add environment variable: `DATA_DIR` = `/tmp/birthday-data`
   (the only writable place on Vercel — and it is temporary).
5. **Deploy.**

**To make Vercel actually work for real storage** you would need to change the app so
files go to an external service (e.g. Cloudinary, AWS S3, Supabase Storage) instead of
the local disk, and move accounts into a database (e.g. Supabase/Postgres). Say the
word and I can rework the app for that.

---

## Which should you pick?

- **Want it to just work and keep every video?** → **Render** (Option A).
- **Just want a quick public demo link?** → Vercel works, but nothing uploaded survives.
