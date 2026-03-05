# AWS EC2 Deployment Guide 🚀

Complete guide to deploy your Trading Bot on AWS EC2 for 24/7 operation.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create EC2 Instance](#2-create-ec2-instance)
3. [Get Elastic IP (Optional)](#3-get-elastic-ip-optional-but-recommended)
4. [Connect to EC2](#4-connect-to-ec2)
5. [Run Setup Script](#5-run-setup-script)
6. [Configure Environment](#6-configure-environment)
7. [Start the Bot](#7-start-the-bot)
8. [Daily Operations](#8-daily-operations)
9. [Monitoring](#9-monitoring)
10. [Troubleshooting](#10-troubleshooting)
11. [Cost Estimate](#11-cost-estimate)
12. [Security Checklist](#12-security-checklist)
13. [Backup Strategy](#13-backup-strategy)
14. [Upgrading Instance](#14-upgrading-instance)
15. [FAQ](#15-faq)

---

## 1. Prerequisites

Before starting, make sure you have:

### ✅ Required

| Item | Description |
|------|-------------|
| **AWS Account** | Free tier works! [Create one here](https://aws.amazon.com/free/) |
| **GitHub Repository** | Your bot code pushed to GitHub |
| **Dhan API Keys** | From [Dhan Developer Portal](https://api.dhan.co/) |
| **Telegram Bot Token** | From [@BotFather](https://t.me/BotFather) |
| **Telegram Chat ID** | Your Telegram user ID |

### 📋 Optional but Recommended

| Item | Description |
|------|-------------|
| **Finnhub API Key** | From [Finnhub](https://finnhub.io/) for news sentiment |
| **SSH Client** | Built into Mac/Linux; use PowerShell on Windows |

### 💡 Skill Requirements

- Basic command line usage
- Ability to edit text files
- GitHub account with your code

---

## 2. Create EC2 Instance

### Step 2.1: Go to EC2 Dashboard

1. Log into [AWS Console](https://console.aws.amazon.com/)
2. Search for "EC2" in the top search bar
3. Click **EC2** to open the dashboard
4. Click the orange **Launch Instance** button

### Step 2.2: Configure Instance

#### Name and Tags