# Deploying the Dashboard on Oracle Cloud Always Free

This walks you through putting the dashboard on a **free forever** Oracle
Cloud VM. End result: the team gets a single URL with a username/password
login. Once set up, nobody needs to touch the server again.

**Total time**: ~30 minutes, one-time.

---

## Part 1 — Create the VM (Oracle Cloud web UI, ~15 min)

### 1.1 Sign up

1. Go to <https://www.oracle.com/cloud/free/>
2. Click **Start for free** and create an account (requires a credit card for
   identity verification — **you won't be charged** for Always Free resources).
3. Account approval is usually instant but can take a few hours.

### 1.2 Create a Compute instance

1. In the Oracle Cloud console, top-left menu → **Compute** → **Instances**.
2. Click **Create instance**.
3. Fill in:
   - **Name**: `visibility-dashboard`
   - **Image**: click *Change image* → **Ubuntu** → **Ubuntu 22.04**
   - **Shape**: click *Change shape* → **Ampere** → pick
     `VM.Standard.A1.Flex`. Set **OCPUs: 1** and **Memory: 6 GB**.
     (This stays under the Always Free limit. You can go up to 4 OCPU / 24 GB
     free but 1/6 is plenty.)
   - **Networking**: leave defaults (it creates a VCN automatically). Make
     sure **Assign a public IPv4 address** is checked.
   - **SSH keys**: choose **Generate a key pair for me**, then click both
     **Save private key** and **Save public key**. Keep the private `.key`
     file — you'll need it to SSH in.
4. Click **Create**. Wait ~1 minute for the status to turn green **Running**.
5. Copy the **Public IP Address** from the instance page — you'll paste this
   a few times.

### 1.3 Open port 80 in the cloud firewall

Oracle's default firewall blocks port 80. Open it once:

1. From the instance page, click the **Virtual cloud network** link (under
   *Primary VNIC*).
2. Under *Resources* → **Security Lists**, click **Default Security List…**
3. Click **Add Ingress Rules**:
   - **Source CIDR**: `0.0.0.0/0`
   - **IP Protocol**: `TCP`
   - **Destination Port Range**: `80`
   - Click **Add Ingress Rules**.

---

## Part 2 — Install the dashboard (SSH, ~10 min)

### 2.1 SSH into the VM

From your Mac terminal:

```bash
chmod 600 ~/Downloads/ssh-key-*.key          # the file you saved earlier
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<PUBLIC_IP>
```

You're now on the VM as user `ubuntu`.

### 2.2 Clone the repo

```bash
cd ~
git clone https://github.com/krishna-uplers/llm-visibility.git Uplers-llm-visibility
cd Uplers-llm-visibility
```

### 2.3 Add API keys

```bash
cp dashboard/deploy/.env.example .env
nano .env
```

Paste each API key (OpenAI, Anthropic, Google, xAI, Perplexity). Save with
`Ctrl+O` → `Enter` → `Ctrl+X`.

### 2.4 Run the installer

```bash
bash dashboard/deploy/setup.sh
```

You'll be asked to pick a username for basic auth, then a password (twice).
Remember these — you'll share them with the team. When the script finishes
it prints the public URL.

---

## Part 3 — Share with the team

Send the team:

- **URL**: `http://<PUBLIC_IP>`
- **Username**: the one you created
- **Password**: the one you created

Any browser on any device works. They bookmark it and use it.

---

## Common tasks (for whoever maintains the server)

**Restart the app**

```bash
sudo systemctl restart visibility-dashboard
```

**Check it's running**

```bash
sudo systemctl status visibility-dashboard
```

**View logs**

```bash
tail -f /var/log/visibility-dashboard.log
```

**Deploy code changes**

```bash
cd ~/Uplers-llm-visibility
git pull
cd dashboard
./venv/bin/pip install -r requirements.txt --quiet
sudo systemctl restart visibility-dashboard
```

**Add another team member to basic auth**

```bash
sudo htpasswd /etc/nginx/.htpasswd alice
```

**Change API keys**

```bash
nano ~/Uplers-llm-visibility/.env
sudo systemctl restart visibility-dashboard
```

---

## Upgrades (optional, later)

- **Custom domain + HTTPS**: point a domain at the public IP, then run
  `sudo apt install certbot python3-certbot-nginx && sudo certbot --nginx`.
  You'll get `https://dashboard.yourdomain.com` with a free TLS cert that
  auto-renews.
- **SSO instead of basic auth**: put Cloudflare Access (free up to 50 users)
  in front — removes the shared password. Requires a Cloudflare domain.
- **Remove port-80 exposure entirely**: run `cloudflared` on the VM and use
  Cloudflare Tunnel — no public ports open at all. Most secure option.

---

## Troubleshooting

**Browser shows nothing / times out**
- Port 80 is closed on Oracle's firewall. Re-check Part 1.3.
- `sudo systemctl status nginx` — is nginx running?

**502 Bad Gateway**
- The FastAPI app isn't running. `sudo systemctl status visibility-dashboard`
  and `tail /var/log/visibility-dashboard.log`.

**"Authorization required" but no password box**
- Some browsers cache 401s. Close all tabs of the site and retry.

**Audit starts but no LLM returns results**
- API keys in `.env` are wrong or empty. Fix and `sudo systemctl restart
  visibility-dashboard`.
