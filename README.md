# OSF Project Checklist

A hosted FastAPI application that lets a user connect an OSF account and review all accessible OSF projects and components—including private nodes—in a hierarchical checklist.

## User flow

### Recommended: Personal Access Token

1. Open the app.
2. Create a read-only OSF Personal Access Token.
3. Paste it into the app.
4. Search, filter, check, and export the hierarchy.
5. Select **Disconnect** to clear the session.

This path bypasses OSF OAuth and CAS entirely.

### Optional: OSF OAuth

OAuth remains available as a secondary path.

## 1. Create an OSF OAuth application

Create an OSF OAuth application and give it this callback URL:

- Local: `http://127.0.0.1:8000/callback/osf`
- Render: `https://YOUR-RENDER-SERVICE.onrender.com/callback/osf`

Record the client ID and client secret.

## 2. Test locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Export the values from `.env`, or run:

```bash
export OSF_CLIENT_ID="..."
export OSF_CLIENT_SECRET="..."
export OSF_REDIRECT_URI="http://127.0.0.1:8000/callback/osf"
export SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
export COOKIE_HTTPS_ONLY=false
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000`.

## 3. Deploy to Render

1. Push this folder to a GitHub repository.
2. In Render, select **New → Blueprint** and connect the repository.
3. Enter:
   - `OSF_CLIENT_ID`
   - `OSF_CLIENT_SECRET`
   - `OSF_REDIRECT_URI=https://YOUR-RENDER-SERVICE.onrender.com/callback/osf`
4. Update the callback URL in the OSF OAuth application to exactly match the Render URL.
5. Deploy.

## Security model

- The app requests the `osf.full_read` OAuth scope.
- It performs no OSF write operations.
- The access token is encrypted before being stored in the signed, HTTP-only session cookie.
- Checklist state is stored in browser local storage.
- Project metadata is fetched when the checklist is opened and is not written to a database.
- Treat exported CSV files as private because they may contain private project titles and GUIDs.

## Production hardening

For a broad public launch, use a server-side session store rather than cookie-contained encrypted tokens, add a privacy notice, set an explicit data-retention policy, and conduct the normal application security review.
