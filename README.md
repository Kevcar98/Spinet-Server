# Spinet Server

Your own music library for the Spinet apps. It is a small server you host
yourself, which stores your music and plays it back to the apps. You can upload
songs from your phone or PC, browse folders as playlists, stream and delete. It
starts with one `docker compose up`.

It only serves your own files. It doesn't search or fetch anything from anywhere
else; it is just your library, on a machine you control.

| Repo | What it is |
|---|---|
| Spinet-Server (this one) | The server |
| [Spinet-Desktop](https://github.com/Kevcar98/Spinet-Desktop) | Spinet for Windows, macOS and Linux |
| [Spinet-Mobile](https://github.com/Kevcar98/Spinet-Mobile) | Spinet for Android |

The apps work without a server. The server is what lets your library, playlists,
likes and play counts follow you from one device to another.

Setting it up takes about 20 to 30 minutes on a free Oracle Cloud server, and
costs nothing to keep running.

**Video guide:** the whole setup, step by step: <https://youtu.be/D1HYXSgLIoI>

**What you need:** a Windows PC to connect from, an email address and a bank
card for Oracle's sign-up (the free tier doesn't charge it), and nothing else.
No coding.

> **Out of the box the server has no password.** Anyone who knows its
> address can play, upload and delete your music. You can
> [turn on a username and password](#optional-turn-on-sign-in) at any time.
> Either way, keep the address to yourself, and prefer HTTPS: it keeps the
> address and password from being read off the network.

## Setup: HTTPS (with domain) or plain HTTP (IP only)?

| Setup | Domain required? | HTTPS? |
|-------|------------------|--------|
| **HTTPS** (recommended) | A hostname, which [Duck DNS](https://www.duckdns.org) gives away free | Yes, automatic |
| **Plain HTTP** (IP only) | No, just your server IP | No |

- **Have a domain or want a free one?** Follow **[HTTPS setup](#https-setup-with-domain)** (steps 1 to 10).
- **Just IP, LAN or testing?** Skip to **[Plain HTTP setup](#plain-http-setup-no-domain-ip-only)**.

---

## HTTPS setup (with domain)

### 1. Create a free Oracle Cloud server

1. Sign up at <https://www.oracle.com/cloud/free/> (a card is required for identity;
   Always Free resources don't charge).
2. **Compute > Instances > Create instance.**
   - **Image:** Canonical **Ubuntu 22.04**.
   - **Shape:** *Ampere* > **VM.Standard.A1.Flex** > **1 OCPU / 6 GB** is plenty
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

Oracle's default public IP is **ephemeral**, which means it can change if the instance stops
and restarts, and your domain would then point at nothing. Make it permanent,
still free:

1. Oracle console > **Networking > IP Management > Reserved Public IPs**.
2. **Create Reserved Public IP.**
3. Open your instance > **Networking** (or **Attached VNICs**) > click the
   VNIC > **IP administration** (or **IPv4 addresses**). It takes two edits
   of the row marked **(Primary IP)**, because the reserved option only shows
   once the ephemeral IP is gone:
   - the **three-dot menu > Edit** > **No public IP** > **Update**.
   - the **three-dot menu > Edit** again > **Reserved public IP** > pick the one you made >
     **Update**.

   (Or, after the first edit: **Reserved Public IPs** > your IP > the **three-dot menu > Edit**
   > assign it to the instance's primary private IP.)

   Don't use **Assign secondary private IP address**: that puts the reserved
   IP on a second address the server doesn't listen on. The Primary IP row
   should end up showing your reserved IP, and there should be only one row.
   If you're connected with PuTTY, reconnect to the new IP.

Use this reserved IP everywhere below.

### 3. Connect to it (PuTTY)

1. Download **PuTTY** (and **PuTTYgen**, bundled with it): <https://www.putty.org/>
2. Oracle's key download is an OpenSSH key, but PuTTY needs its own `.ppk` format,
   so convert it first:
   - Open **PuTTYgen** > **Conversions > Import key** > pick the private key
     Oracle gave you.
   - **Save private key** > save as e.g. `oracle-key.ppk`.
3. Open **PuTTY**:
   - **Host Name:** `ubuntu@<instance-public-ip>`
   - **Port:** 22
   - Left tree > **Connection > SSH > Auth > Credentials** > **Private key
     file for authentication** > browse to `oracle-key.ppk`.
   - (Optional) Back in **Session**, save it under **Saved Sessions**.
4. **Open** > accept the host key prompt on first connect > you're in.

Run everything below **inside that PuTTY session**.

### 4. Open the firewall (two layers, both needed)

**Cloud side:** open your instance > its **subnet** (or VCN) > **Security**
tab > the **Security list** > **Security rules** > **Add Ingress Rules**. For
each port you need to add: **Source CIDR** `0.0.0.0/0`, **IP Protocol** TCP, **Destination
Port Range** the port, Source Port Range left empty.

| Port | Purpose |
|-----:|---------|
| 22   | SSH (PuTTY). **Already open by default**, nothing to add |
| 80   | HTTP, needed to issue the free certificate |
| 443  | HTTPS, what the apps connect to |

Don't open 8091 for HTTPS: the apps come in on 443, and Caddy passes that on
to the library inside the server, where 8091 stays private.

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

**Free: Duck DNS** (two minutes, no card)

1. Go to <https://www.duckdns.org> and sign in with Google/GitHub/Reddit.
2. Type a name, say `spinet-kev`, and press **add domain**. You now own
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

Clone it straight from GitHub in your PuTTY session. No file-transfer tool is needed:

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
shows up right away. Otherwise it starts empty and you upload from the app later.

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

In Spinet, open **Settings > My Servers**, enter `<your-domain>`, choose
**HTTPS** and press **Save**. Your library, uploads and playback now go through
your own server.

---

## Plain HTTP setup (no domain, IP only)

A complete walkthrough with no domain, just your server's IP on port 8091.

### 1. Create a free Oracle Cloud server

1. Sign up at <https://www.oracle.com/cloud/free/> (a card is required for identity;
   Always Free resources don't charge).
2. **Compute > Instances > Create instance.**
   - **Image:** Canonical **Ubuntu 22.04**.
   - **Shape:** *Ampere* > **VM.Standard.A1.Flex** > **1 OCPU / 6 GB** is plenty
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

Oracle's default public IP is **ephemeral**, which means it can change if the instance stops
and restarts, breaking your URL. Make it permanent, still free:

1. Oracle console > **Networking > IP Management > Reserved Public IPs**.
2. **Create Reserved Public IP.**
3. Open your instance > **Networking** (or **Attached VNICs**) > click the
   VNIC > **IP administration** (or **IPv4 addresses**). It takes two edits
   of the row marked **(Primary IP)**, because the reserved option only shows
   once the ephemeral IP is gone:
   - the **three-dot menu > Edit** > **No public IP** > **Update**.
   - the **three-dot menu > Edit** again > **Reserved public IP** > pick the one you made >
     **Update**.

   (Or, after the first edit: **Reserved Public IPs** > your IP > the **three-dot menu > Edit**
   > assign it to the instance's primary private IP.)

   Don't use **Assign secondary private IP address**: that puts the reserved
   IP on a second address the server doesn't listen on. The Primary IP row
   should end up showing your reserved IP, and there should be only one row.
   If you're connected with PuTTY, reconnect to the new IP.

### 3. Connect to it (PuTTY)

1. Download **PuTTY** (and **PuTTYgen**, bundled with it): <https://www.putty.org/>
2. Oracle's key download is an OpenSSH key, but PuTTY needs its own `.ppk` format,
   so convert it first:
   - Open **PuTTYgen** > **Conversions > Import key** > pick the private key
     Oracle gave you.
   - **Save private key** > save as e.g. `oracle-key.ppk`.
3. Open **PuTTY**:
   - **Host Name:** `ubuntu@<your-reserved-ip>`
   - **Port:** 22
   - Left tree > **Connection > SSH > Auth > Credentials** > **Private key
     file for authentication** > browse to `oracle-key.ppk`.
   - (Optional) Back in **Session**, save it under **Saved Sessions**.
4. **Open** > accept the host key prompt on first connect > you're in.

Run everything below **inside that PuTTY session**.

### 4. Open the firewall (two layers, both needed)

For plain HTTP the only port to add is **8091**, the one the apps connect to.

**Cloud side:** open your instance > its **subnet** (or VCN) > **Security**
tab > the **Security list** > **Security rules** > **Add Ingress Rules**. For
each port you need to add: **Source CIDR** `0.0.0.0/0`, **IP Protocol** TCP, **Destination
Port Range** the port, Source Port Range left empty.

| Port | Purpose |
|-----:|---------|
| 22   | SSH (PuTTY). **Already open by default**, nothing to add |
| 8091 | The library server, what the apps connect to |

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

Then check from your own PC that both firewalls let it through: open
`http://<your-reserved-ip>:8091/health` in a browser. It should show
`{"status":"ok",...}`. If it works on the server but not from your PC, one of
the two firewall layers in step 4 is still closed.

### 8. Add it to the app

In Spinet, open **Settings > My Servers**, enter `<your-reserved-ip>`, choose
**HTTP**, set the port to **8091** and press **Save**. Your library, uploads
and playback now go through your own server.

---

## Optional: turn on sign-in

Make the server ask for a username and password. Leave it off and nothing
changes. Needs the Spinet apps from version 0.0.1 (the October 2026 fresh start) or later.

1. Connect with PuTTY and go to the server's folder:

   ```bash
   cd ~/spinet-server
   ```

2. Plain HTTP setups have no `.env` yet; make one (HTTPS setups skip this):

   ```bash
   cp .env.example .env
   ```

3. Set your username and password. Run this, type your password twice
   (nothing shows while you type), and enter a username if it asks:

   ```bash
   python3 local/library/hash_password.py .env
   ```

   Only a hash of the password is saved in `.env`, never the password itself.
   Then restart the server so it picks it up, using the line for your setup:

   ```bash
   docker compose up -d                                  # HTTPS
   ```

   ```bash
   docker compose -f docker-compose.http.yml up -d       # plain HTTP
   ```

4. If you ever want to see what was saved, `.env` ends with two lines like:

   ```
   SPINET_USERNAME=kev
   SPINET_PASSWORD_HASH='pbkdf2_sha256:600000:...'
   ```

5. Check it's on: `curl "http://localhost:8091/health"` (plain HTTP) or
   `curl "https://<your-domain>/health"` (HTTPS) should show `"auth":true`.

6. In **each** Spinet app: **Settings > My Servers**, press **Edit** on this server, fill in **Username** and
   **Password**, and press **Save**. It should say **"Server configured and signed in."**

**Good to know**

- **Use a long password.** With sign-in on, it's what stands between the
  internet and your library. After 10 wrong attempts from one connection in
  10 minutes, that connection is refused for 10 minutes.
- **Plain HTTP sends the password unencrypted.** Sign-in still stops casual
  use of your server, but over HTTPS nobody on the way can read it.
- **To change the password**, run step 3 again, then save the new password in
  each app. Songs keep playing, since the apps ask the server for a
  fresh link each time, but some covers saved with your likes and playlists
  may show blank after the change.
- **To turn sign-in off**, empty both lines in `.env` and restart.
- **Older setups** with a `SPINET_PASSWORD` line still work, but that keeps the
  password in plain text. Run step 3 to replace it with a hash.
- The `/health` check stays open, so the apps can tell "wrong address" from
  "needs a password". It only says the server is up and that sign-in is on.

## Updating

When this repo changes, bring your server up to date. Your music and your `.env`
are kept; only the server's code is replaced.

1. Connect with PuTTY (your saved session).
2. Go to the server's folder:

   ```bash
   cd ~/spinet-server
   ```

3. Fetch the new version and rebuild, using the line for your setup:

   ```bash
   git fetch && git reset --hard origin/master && docker compose up -d --build                              # HTTPS
   ```

   ```bash
   git fetch && git reset --hard origin/master && docker compose -f docker-compose.http.yml up -d --build   # plain HTTP
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

- The update replaces any changes you made to the server's own files with the
  latest version. Your `.env` and music are never affected, as git ignores
  them.
- The health check fails: look at what the server says with
  `docker compose logs --tail 50` (add `-f docker-compose.http.yml` after
  `compose` for plain HTTP).
- To clear out old build leftovers now and then: `docker image prune -f`.

## Adding music

- Drop files (or whole folders; each folder becomes a playlist) into
  `local/library/music/` on the server, then hit **rescan** from the app or
  `curl -X POST .../rescan`.
- Or upload straight from the app. Anything you save to the server lands here.
- Cover art/artist come from the files' own tags; missing art is filled in from
  the free iTunes lookup (set `LIBRARY_ONLINE_ENRICH=0` to stay fully offline).

## Transfer history

Every upload and delete is appended to `.spinet_transfers.jsonl` in the music
folder, one JSON object per line, hidden from the audio scan, and kept in the
same volume as your music so it survives rebuilds. Read it back:

```bash
curl -s .../transfers?limit=50
curl -s ".../transfers?folder=My%20Playlist"
```

Each entry has `at` (epoch ms), `event` (`upload`/`delete`), `file`, `folder`,
`title`, `artist`, and `size` for uploads. Useful when you want the history from
a device that didn't do the transfer. The app keeps its own local copy, but
this one belongs to the library. Delete the file to reset it; nothing depends on
it existing.

## Notes

- This is your own server. Nobody else needs to run anything.
- Without [sign-in](#optional-turn-on-sign-in), whoever has the address can
  use it, including deleting music. Only give the address to your own apps.
- Keep `.env` private (holds your domain config, and your sign-in if you set one). Your music stays on the server;
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
