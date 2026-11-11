# PolarIS

### Remote Installation

Install PolarIS on a remote computer.

URL <https://iharpv.cs.umn.edu>

Install under `/opt/polar-is`.

```bash
sudo apt update
sudo apt install -y \
    git python3.12 python3.12-venv \
    nodejs npm nginx certbot python3-certbot-nginx

sudo mkdir -p /opt/polar-is
sudo chown "$USER":"$USER" /opt/polar-is

git clone \
    --branch v3-trial \
    --single-branch \
    https://github.com/ana-e-uk/polar-is.git \
    /opt/polar-is

cd /opt/polar-is
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[plot]'

cd api/interface/frontend
npm ci
npm run build
cd /opt/polar-is
```