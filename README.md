# Spinet Server

Your own **cloud music library** for the **Spinet** app. A small self-hosted
server that stores your music and serves it back to the app — upload from the
phone, browse folders as playlists, stream, and delete. One `docker compose up`.

It only ever serves **your own files**. No search engines, no extraction, nothing
fetched from anywhere — just your library on a box you control.

| | |
|---|---|
| ☁️ **This repo** | The server |
| 💻 **Desktop app** | [Spinet-Desktop](https://github.com/Kevcar98/Spinet-Desktop) — Windows, macOS, Linux |
| 📱 **Android app** | [Spinet-Mobile](https://github.com/Kevcar98/Spinet-Mobile) |

The apps work without a server; this is what makes a library follow you between
them — playlists, likes and play counts included.

Takes ~20–30 minutes on a free Oracle Cloud server, no ongoing cost.

**What you need:** a Windows PC to connect from, an email address and a bank
card for Oracle's sign-up (the free tier doesn't charge it), and nothing else.
No coding.

> **The server has no password.** Anyone who knows its address can play,
> upload and delete your music. Treat the address like a password: don't post
> it anywhere, and only enter it in your own apps. HTTPS keeps it from being
> read off the network, so prefer it when you can.

## Fastest: one-click setup on Oracle Cloud

The button below creates the whole server in your own free Oracle Cloud
account: network, firewall, a fixed public IP, and Spinet Server installed and
running. No PuTTY, no commands. About 15 minutes, most of it waiting.

[![Deploy to Oracle Cloud](https://oci-resourcemanager-plugin.plugins.oci.oraclecloud.com/latest/deploy-to-oracle-cloud.svg)](https://cloud.oracle.com/resourcemanager/stacks/create?zipUrl=https://github.com/Kevcar98/Spinet-Server/releases/download/oracle-stack/spinet-server-oracle-stack.zip)

**1. Before you click** (only for the setup you'll pick):

- **Free DuckDNS name (recommended):** go to <https://www.duckdns.org>, sign
  in, type a name (say `spinet-kev`) and press **add domain**. Leave the IP
  as it is: the server fills it in. Copy the **token** shown at the top of the
  page.
- **Your own domain:** nothing yet. You'll point it at the server at the end.
- **Plain HTTP with just the IP:** nothing. Works straight away, but isn't
  encrypted.
- **Optional, for updating the server later:** make an SSH key. Open
  **PuTTYgen** (comes with [PuTTY](https://www.putty.org/)) → **Generate** →
  wiggle the mouse → **Save private key** (e.g. `spinet-key.ppk`, keep it
  safe) → copy the text in the box at the top, which is your public key.

**2. Click the button.** Sign up for Oracle Cloud if you haven't (a card is
needed for identity; Always Free resources don't charge), and sign in.

**3. Fill in the form.** Tick the box to accept the terms if asked, then
**Next**:

- **Setup:** pick one of the three, and fill in the DuckDNS name and token, or
  your domain.
- **Availability domain:** leave the first. If creating fails with "out of
  capacity", run it again with another one, or pick the AMD server type.
- **SSH public key:** paste the public key from step 1, or leave it empty.

**Next** again, keep **Run apply** ticked, and **Create**.

**4. Wait for the job** to say **Succeeded** (5–10 minutes). Open
**Application information** (or **Outputs**): it shows the address to use.
The server needs about 5 more minutes after that to finish installing.

**5. Own domain only:** add an A record for your hostname pointing at the
**Server IP** shown. HTTPS starts working once it resolves.

**6. Add it to the app:** **Settings → My Server** → **Host:** the address
from step 4 → **Save**.

To update the server later, connect with PuTTY as `ubuntu@<server-ip>` using
the `.ppk` key from step 1, and follow [Updating](#updating). Without a key,
you can't connect to update it, but it keeps working as it is.

The manual walkthroughs below do the same by hand.

---

## Manual setup: HTTPS (with domain) or plain HTTP (IP only)?

| Setup | Domain required? | HTTPS? |
|-------|------------------|--------|
| **HTTPS** (recommended) | A hostname, which [Duck DNS](https://www.duckdns.org) gives away free | Yes, automatic |
| **Plain HTTP** (IP only) | No — just your server IP | No |

- **Have a domain or want a free one?** Follow **[HTTPS setup](#https-setup-with-domain)** (steps 1–10).
- **Just IP, LAN or testing?** Skip to **[Plain HTTP setup](#plain-http-setup-no-domain-ip-only)**.

---

## HTTPS setup (with domain)

### 1. Create a free Oracle Cloud server

1. Sign up at <https://www.oracle.com/cloud/free/> (a card is required for identity;
   Always Free resources don't charge).
2. **Compute → Instances → Create instance.**
   - **Image:** Canonical **Ubuntu 22.04**.
   - **Shape:** *Ampere* → **VM.Standard.A1.Flex** → **1 OCPU / 6 GB** is plenty
     (still Always Free). If Ampere is unavailable in your region, the AMD
     **VM.Standard.E2.1.Micro** also works.
   - **Capacity type** (under advanced options, if shown): **On-demand**. Not
     *Dedicated host* (it costs money) or *Preemptible* (Oracle can stop it at
     any time). An "out of capacity" error just means try again later, or use
     the E2.1.Micro shape.
   - **Networking:** make sure **Assign a public IPv4 address** is on.
     Everything else there (private DNS record, hostname, launch options) can
     stay as it is.
   - **SSH keys:** upload your public key (or let it generate + download one).
3. Create it, and note the instance's **public IP**.

### 2. Reserve your public IP (don't skip this)

Oracle's default public IP is **ephemeral** — it can change if the instance stops
and restarts, and your domain would then point at nothing. Make it permanent,
still free:

1. Oracle console → **Networking → IP Management → Reserved Public IPs**.
2. **Create Reserved Public IP.**
3. Open your instance → **Networking** (or **Attached VNICs**) → click the
   VNIC → **IP administration** (or **IPv4 addresses**). It takes two edits
   of the row marked **(Primary IP)**, because the reserved option only shows
   once the ephemeral IP is gone:
   - **⋯ → Edit** → **No public IP** → **Update**.
   - **⋯ → Edit** again → **Reserved public IP** → pick the one you made →
     **Update**.

   (Or, after the first edit: **Reserved Public IPs** → your IP → **⋯ → Edit**
   → assign it to the instance's primary private IP.)

   Don't use **Assign secondary private IP address**: that puts the reserved
   IP on a second address the server doesn't listen on. The Primary IP row
   should end up showing your reserved IP, and there should be only one row.
   If you're connected with PuTTY, reconnect to the new IP.

Use this reserved IP everywhere below.

### 3. Connect to it (PuTTY)

1. Download **PuTTY** (and **PuTTYgen**, bundled with it): <https://www.putty.org/>
2. Oracle's key download is an OpenSSH key — PuTTY needs its own `.ppk` format,
   so convert it first:
   - Open **PuTTYgen** → **Conversions → Import key** → pick the private key
     Oracle gave you.
   - **Save private key** → save as e.g. `oracle-key.ppk`.
3. Open **PuTTY**:
   - **Host Name:** `ubuntu@<instance-public-ip>`
   - **Port:** 22
   - Left tree → **Connection → SSH → Auth → Credentials** → **Private key
     file for authentication** → browse to `oracle-key.ppk`.
   - (Optional) Back in **Session**, save it under **Saved Sessions**.
4. **Open** → accept the host key prompt on first connect → you're in.

Run everything below **inside that PuTTY session**.

### 4. Open the firewall (two layers — both needed)

**Cloud side:** in the Oracle console → your instance's VCN → subnet → Security
List → add **Ingress** rules, source `0.0.0.0/0`:

| Port | Purpose |
|-----:|---------|
| 22   | SSH |
| 80   | HTTP (cert issuing) |
| 443  | HTTPS |

**Inside the VM** (Oracle images ship a locked-down firewall too):

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80  -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

### 5. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Reconnect (reopen PuTTY, same saved session), then confirm:

```bash
docker --version && docker compose version
```

### 6. Point your domain at it

You do **not** need to buy one. Either works:

**Free — Duck DNS** (two minutes, no card)

1. Go to <https://www.duckdns.org> and sign in with Google/GitHub/Reddit.
2. Type a name — say `spinet-kev` — and press **add domain**. You now own
   `spinet-kev.duckdns.org`.
3. Put your reserved IP in the **current ip** box and press **update ip**.

That name is the whole hostname: there is no subdomain to add.

**A domain of your own**

Add one A record pointing at your reserved IP, for example
`library.example.com`.

Either way, check it resolves before going further:

```bash
nslookup spinet-kev.duckdns.org
```

DNS has to resolve **before** you start the stack: the certificate is issued by
a server that visits that name, and it cannot do that if the name points
nowhere.

### 7. Get this repo onto the server (git)

Clone it straight from GitHub in your PuTTY session — no file-transfer tool needed:

```bash
sudo apt update && sudo apt install -y git
cd ~
git clone https://github.com/Kevcar98/Spinet-Server.git spinet-server
cd spinet-server
```

It's a public repo, so no login.

### 8. Configure it

```bash
cd ~/spinet-server

cp .env.example .env
nano .env                  # DOMAIN = the exact hostname from step 6
```

`DOMAIN` is the whole host, not just the registered part. In nano, change the
`DOMAIN=` line, then **Ctrl+O**, **Enter** to save and **Ctrl+X** to quit:

```
DOMAIN=spinet-kev.duckdns.org      # free Duck DNS name
DOMAIN=library.example.com         # your own domain
```

*(Optional)* Put your own music in `local/library/music/` now, so your library
shows up right away — otherwise it starts empty and you upload from the app later.

### 9. Start it

```bash
docker compose up -d
docker compose logs -f caddy library
```

Give it a minute for the HTTPS certificate, then check:

```bash
curl "https://<your-domain>/health"      # {"status":"ok",...}
curl "https://<your-domain>/playlists"   # your folders
```

Press **Ctrl+C** to stop following the logs; the server keeps running.

A certificate error here almost always means DNS was not resolving yet when the
stack started. Fix the record, then `docker compose restart caddy`.

### 10. Add it to the app

In Spinet: **Settings → My Server** → **Host:** `https://<your-domain>`
→ **Save**. Your library, uploads, and playback now route through your own server.

---

## Plain HTTP setup (no domain, IP only)

A complete, standalone walkthrough — no domain, just your server's IP on port 8091.

### 1. Create a free Oracle Cloud server

1. Sign up at <https://www.oracle.com/cloud/free/> (a card is required for identity;
   Always Free resources don't charge).
2. **Compute → Instances → Create instance.**
   - **Image:** Canonical **Ubuntu 22.04**.
   - **Shape:** *Ampere* → **VM.Standard.A1.Flex** → **1 OCPU / 6 GB** is plenty
     (still Always Free). If Ampere is unavailable in your region, the AMD
     **VM.Standard.E2.1.Micro** also works.
   - **Capacity type** (under advanced options, if shown): **On-demand**. Not
     *Dedicated host* (it costs money) or *Preemptible* (Oracle can stop it at
     any time). An "out of capacity" error just means try again later, or use
     the E2.1.Micro shape.
   - **Networking:** make sure **Assign a public IPv4 address** is on.
     Everything else there (private DNS record, hostname, launch options) can
     stay as it is.
   - **SSH keys:** upload your public key (or let it generate + download one).
3. Create it, and note the instance's **public IP**.

### 2. Reserve your public IP (don't skip this)

Oracle's default public IP is **ephemeral** — it can change if the instance stops
and restarts, breaking your URL. Make it permanent, still free:

1. Oracle console → **Networking → IP Management → Reserved Public IPs**.
2. **Create Reserved Public IP.**
3. Open your instance → **Networking** (or **Attached VNICs**) → click the
   VNIC → **IP administration** (or **IPv4 addresses**). It takes two edits
   of the row marked **(Primary IP)**, because the reserved option only shows
   once the ephemeral IP is gone:
   - **⋯ → Edit** → **No public IP** → **Update**.
   - **⋯ → Edit** again → **Reserved public IP** → pick the one you made →
     **Update**.

   (Or, after the first edit: **Reserved Public IPs** → your IP → **⋯ → Edit**
   → assign it to the instance's primary private IP.)

   Don't use **Assign secondary private IP address**: that puts the reserved
   IP on a second address the server doesn't listen on. The Primary IP row
   should end up showing your reserved IP, and there should be only one row.
   If you're connected with PuTTY, reconnect to the new IP.

### 3. Connect to it (PuTTY)

1. Download **PuTTY** (and **PuTTYgen**, bundled with it): <https://www.putty.org/>
2. Oracle's key download is an OpenSSH key — PuTTY needs its own `.ppk` format,
   so convert it first:
   - Open **PuTTYgen** → **Conversions → Import key** → pick the private key
     Oracle gave you.
   - **Save private key** → save as e.g. `oracle-key.ppk`.
3. Open **PuTTY**:
   - **Host Name:** `ubuntu@<your-reserved-ip>`
   - **Port:** 22
   - Left tree → **Connection → SSH → Auth → Credentials** → **Private key
     file for authentication** → browse to `oracle-key.ppk`.
   - (Optional) Back in **Session**, save it under **Saved Sessions**.
4. **Open** → accept the host key prompt on first connect → you're in.

Run everything below **inside that PuTTY session**.

### 4. Open the firewall (two layers — both needed)

For plain HTTP the only port you need open is **8091**.

**Cloud side:** in the Oracle console → your instance's VCN → subnet → Security
List → add **Ingress** rules, source `0.0.0.0/0`:

| Port | Purpose |
|-----:|---------|
| 22   | SSH |
| 8091 | Library server |

**Inside the VM** (Oracle images ship a locked-down firewall too):

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8091 -j ACCEPT
sudo netfilter-persistent save
```

### 5. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```

Reconnect (reopen PuTTY, same saved session), then confirm:

```bash
docker --version && docker compose version
```

### 6. Get this repo onto the server (git)

```bash
sudo apt update && sudo apt install -y git
cd ~
git clone https://github.com/Kevcar98/Spinet-Server.git spinet-server
cd spinet-server
```

It's a public repo, so no login.

### 7. Start it

No `.env` needed for plain HTTP.

```bash
docker compose -f docker-compose.http.yml up -d
docker compose -f docker-compose.http.yml logs -f library
```

Press **Ctrl+C** to stop following the logs; the server keeps running. Check
(locally on the server):

```bash
curl "http://localhost:8091/health"      # {"status":"ok",...}
curl "http://localhost:8091/playlists"   # folders
```

### 8. Add it to the app

In Spinet: **Settings → My Server** → **Host:** `http://<your-reserved-ip>:8091`
→ **Save**. Your library, uploads, and playback now route through your own server.

---

## Updating

When this repo changes, bring your server up to date. Your music and your `.env`
are kept; only the server's code is replaced.

1. Connect with PuTTY (your saved session).
2. Go to the server's folder:

   ```bash
   cd ~/spinet-server
   ```

3. Fetch the new version and rebuild — use the line for your setup:

   ```bash
   git pull && docker compose up -d --build                              # HTTPS
   ```

   ```bash
   git pull && docker compose -f docker-compose.http.yml up -d --build   # plain HTTP
   ```

   `--build` rebuilds the server so the new code takes effect; `-d` keeps it
   running after you disconnect. Expect a minute or two.

4. Check it came back:

   ```bash
   curl "https://<your-domain>/health"       # HTTPS
   ```

   ```bash
   curl "http://localhost:8091/health"       # plain HTTP
   ```

   Both should print `{"status":"ok",...}`. The apps reconnect by themselves.

**If something goes wrong**

- `git pull` complains about local changes: you edited a file the repo also
  changed. `git stash && git pull` sets your edit aside and updates; your
  `.env` and music are never affected, as git ignores them.
- The health check fails: look at what the server says with
  `docker compose logs --tail 50` (add `-f docker-compose.http.yml` after
  `compose` for plain HTTP).
- To clear out old build leftovers now and then: `docker image prune -f`.

## Adding music

- Drop files (or whole folders — each folder becomes a playlist) into
  `local/library/music/` on the server, then hit **rescan** from the app or
  `curl -X POST .../rescan`.
- Or upload straight from the app — anything you save to the server lands here.
- Cover art/artist come from the files' own tags; missing art is filled in from
  the free iTunes lookup (set `LIBRARY_ONLINE_ENRICH=0` to stay fully offline).

## Transfer history

Every upload and delete is appended to `.spinet_transfers.jsonl` in the music
folder — one JSON object per line, hidden from the audio scan, and kept in the
same volume as your music so it survives rebuilds. Read it back:

```bash
curl -s .../transfers?limit=50
curl -s ".../transfers?folder=My%20Playlist"
```

Each entry has `at` (epoch ms), `event` (`upload`/`delete`), `file`, `folder`,
`title`, `artist`, and `size` for uploads. Useful when you want the history from
a device that didn't do the transfer — the app keeps its own local copy, but
this one belongs to the library. Delete the file to reset it; nothing depends on
it existing.

## Notes

- This is **your own** server — nobody else needs to run anything.
- It has **no password**: whoever has the address can use it, including
  deleting music. Only give the address to your own apps.
- Keep `.env` private (holds your domain config). Your music stays on the server;
  it's git-ignored so it never gets committed.

## License

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Spinet Server is Free Software: you can use, study, share, and improve it at
will. Specifically you can redistribute and/or modify it under the terms of the
[GNU General Public License](https://www.gnu.org/licenses/gpl-3.0.html) as
published by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version. Full text: [LICENSE](LICENSE).

The library server links **mutagen** (GPL-2.0-or-later); everything else (FastAPI,
uvicorn, httpx) is permissive (MIT/BSD) and GPL-compatible.
