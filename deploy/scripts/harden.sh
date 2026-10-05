#!/usr/bin/env bash
# One-off server hardening for a fresh Ubuntu 22.04/24.04 VPS. Run once as root, BEFORE
# the app is deployed. It is safe to re-run.
#   - firewall: only SSH, HTTP and HTTPS reachable from outside
#   - fail2ban for SSH and for the Nginx 429/4xx floods
#   - SSH: keys only, no root login
#   - automatic security updates
#   - 2 GB swap so a memory spike degrades gracefully instead of killing MySQL
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ufw fail2ban unattended-upgrades

# --- firewall ---------------------------------------------------------------
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# --- SSH --------------------------------------------------------------------
if [ ! -s /root/.ssh/authorized_keys ] && ! ls /home/*/.ssh/authorized_keys >/dev/null 2>&1; then
    echo "Add your SSH public key first (authorized_keys), then re-run: password login is about to be disabled." >&2
    exit 1
fi
cat > /etc/ssh/sshd_config.d/99-mahitaji.conf <<'SSH'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
MaxAuthTries 4
LoginGraceTime 30
X11Forwarding no
SSH
systemctl reload ssh 2>/dev/null || systemctl reload sshd

# --- fail2ban ---------------------------------------------------------------
cat > /etc/fail2ban/jail.d/mahitaji.local <<'JAIL'
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true

[nginx-limit-req]
enabled  = true
logpath  = /var/log/nginx/error.log
maxretry = 20

[nginx-botsearch]
enabled  = true
logpath  = /var/log/nginx/access.log
maxretry = 10
JAIL
systemctl enable --now fail2ban
systemctl restart fail2ban

# --- automatic security updates --------------------------------------------
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
APT
sed -i 's|^//\s*"\${distro_id}:\${distro_codename}-security";|        "${distro_id}:${distro_codename}-security";|' /etc/apt/apt.conf.d/50unattended-upgrades

# --- swap -------------------------------------------------------------------
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
grep -q 'vm.swappiness' /etc/sysctl.d/99-mahitaji.conf 2>/dev/null || echo 'vm.swappiness=10' > /etc/sysctl.d/99-mahitaji.conf
sysctl -q -p /etc/sysctl.d/99-mahitaji.conf

echo "hardening done: $(ufw status | head -1); fail2ban $(systemctl is-active fail2ban); swap $(swapon --show --noheadings | awk '{print $3}')"
