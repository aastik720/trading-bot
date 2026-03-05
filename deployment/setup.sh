#!/bin/bash

#===============================================================================
# TRADING BOT - EC2 SETUP SCRIPT
#===============================================================================
#
# This script sets up a fresh EC2 instance (Amazon Linux 2023 or Ubuntu 22.04)
# to run the Trading Bot 24/7.
#
# Usage:
#   chmod +x deployment/setup.sh
#   sudo bash deployment/setup.sh
#
# What it does:
#   1. Updates system packages
#   2. Installs Python 3.11+, pip, venv
#   3. Installs git and system dependencies
#   4. Sets up virtual environment
#   5. Installs Python packages
#   6. Configures systemd service
#   7. Creates helper scripts
#
# Requirements:
#   - Fresh EC2 instance (Amazon Linux 2023 or Ubuntu 22.04)
#   - Run as root or with sudo
#   - Internet connection
#
# Author: Trading Bot
# Phase: 9 - AWS Deployment
#===============================================================================

# Exit on any error
set -e

#===============================================================================
# CONFIGURATION
#===============================================================================

# Bot directory (will be detected or set)
BOT_DIR=""
BOT_USER=""
BOT_GROUP=""

# Minimum Python version required
MIN_PYTHON_VERSION="3.10"

# GitHub repository (USER MUST CHANGE THIS)
GITHUB_REPO="USERNAME/trading-bot"

#===============================================================================
# COLORS FOR OUTPUT
#===============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Symbols
CHECK="✓"
CROSS="✗"
ARROW="→"
STAR="★"

#===============================================================================
# HELPER FUNCTIONS
#===============================================================================

print_banner() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║${NC}        ${WHITE}TRADING BOT - EC2 SETUP SCRIPT${NC}                       ${CYAN}║${NC}"
    echo -e "${CYAN}║${NC}        ${PURPLE}Options Trading Bot for NSE${NC}                           ${CYAN}║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_step() {
    local step_num=$1
    local step_msg=$2
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${WHITE}STEP ${step_num}:${NC} ${CYAN}${step_msg}${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_success() {
    echo -e "${GREEN}${CHECK} $1${NC}"
}

print_error() {
    echo -e "${RED}${CROSS} ERROR: $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ WARNING: $1${NC}"
}

print_info() {
    echo -e "${BLUE}${ARROW} $1${NC}"
}

print_substep() {
    echo -e "  ${PURPLE}${ARROW}${NC} $1"
}

# Error handler
handle_error() {
    local line_num=$1
    print_error "Script failed at line ${line_num}"
    print_error "Please check the error message above and try again."
    exit 1
}

# Set up error trap
trap 'handle_error ${LINENO}' ERR

# Check if running as root
check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root or with sudo"
        echo "Usage: sudo bash $0"
        exit 1
    fi
}

# Detect OS
detect_os() {
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        OS=$ID
        OS_VERSION=$VERSION_ID
    elif [[ -f /etc/amazon-linux-release ]]; then
        OS="amzn"
        OS_VERSION="2023"
    else
        print_error "Unable to detect operating system"
        exit 1
    fi
    
    print_info "Detected OS: ${OS} ${OS_VERSION}"
}

# Detect the actual user (not root)
detect_user() {
    # Try to find the actual user who ran sudo
    if [[ -n "${SUDO_USER}" ]]; then
        BOT_USER="${SUDO_USER}"
    elif [[ -d "/home/ec2-user" ]]; then
        BOT_USER="ec2-user"
    elif [[ -d "/home/ubuntu" ]]; then
        BOT_USER="ubuntu"
    else
        BOT_USER=$(ls /home | head -1)
    fi
    
    BOT_GROUP="${BOT_USER}"
    BOT_DIR="/home/${BOT_USER}/trading-bot"
    
    print_info "Bot will run as user: ${BOT_USER}"
    print_info "Bot directory: ${BOT_DIR}"
}

# Check if command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Compare version numbers
version_gte() {
    # Returns 0 (true) if $1 >= $2
    printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

#===============================================================================
# STEP 1: SYSTEM UPDATE
#===============================================================================

step_1_system_update() {
    print_step "1" "Updating System Packages"
    
    case $OS in
        amzn|amazon)
            print_substep "Running: dnf update -y"
            dnf update -y
            ;;
        ubuntu|debian)
            print_substep "Running: apt update && apt upgrade -y"
            apt update
            apt upgrade -y
            ;;
        rhel|centos|fedora)
            print_substep "Running: dnf update -y"
            dnf update -y
            ;;
        *)
            print_warning "Unknown OS: ${OS}. Trying dnf..."
            dnf update -y || yum update -y || apt update
            ;;
    esac
    
    print_success "System packages updated"
}

#===============================================================================
# STEP 2: INSTALL PYTHON
#===============================================================================

step_2_install_python() {
    print_step "2" "Installing Python 3.11+"
    
    # Check if Python 3.11+ already exists
    if command_exists python3.11; then
        PYTHON_CMD="python3.11"
        print_info "Python 3.11 already installed"
    elif command_exists python3.12; then
        PYTHON_CMD="python3.12"
        print_info "Python 3.12 already installed"
    elif command_exists python3; then
        # Check version
        CURRENT_VERSION=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
        if version_gte "$CURRENT_VERSION" "$MIN_PYTHON_VERSION"; then
            PYTHON_CMD="python3"
            print_info "Python ${CURRENT_VERSION} already installed (meets requirements)"
        else
            print_info "Python ${CURRENT_VERSION} is too old. Installing newer version..."
            PYTHON_CMD=""
        fi
    else
        PYTHON_CMD=""
    fi
    
    # Install Python if needed
    if [[ -z "$PYTHON_CMD" ]]; then
        case $OS in
            amzn|amazon)
                print_substep "Installing Python 3.11 via dnf..."
                dnf install -y python3.11 python3.11-pip python3.11-devel
                PYTHON_CMD="python3.11"
                ;;
            ubuntu|debian)
                print_substep "Installing Python 3.11 via apt..."
                # Add deadsnakes PPA for newer Python versions
                apt install -y software-properties-common
                add-apt-repository -y ppa:deadsnakes/ppa || true
                apt update
                apt install -y python3.11 python3.11-venv python3.11-dev python3-pip
                PYTHON_CMD="python3.11"
                ;;
            *)
                print_substep "Installing Python 3 via package manager..."
                dnf install -y python3 python3-pip python3-devel || \
                apt install -y python3 python3-pip python3-venv python3-dev
                PYTHON_CMD="python3"
                ;;
        esac
    fi
    
    # Install venv module
    case $OS in
        amzn|amazon)
            # venv is usually included with python3.11
            print_substep "Ensuring venv is available..."
            ;;
        ubuntu|debian)
            print_substep "Installing python3-venv..."
            apt install -y python3-venv python3.11-venv 2>/dev/null || apt install -y python3-venv
            ;;
    esac
    
    # Verify installation
    print_substep "Verifying Python installation..."
    $PYTHON_CMD --version
    
    # Store python command for later use
    echo "PYTHON_CMD=${PYTHON_CMD}" > /tmp/trading_bot_setup_vars
    
    print_success "Python installed: $($PYTHON_CMD --version)"
}

#===============================================================================
# STEP 3: INSTALL GIT
#===============================================================================

step_3_install_git() {
    print_step "3" "Installing Git"
    
    if command_exists git; then
        print_info "Git already installed: $(git --version)"
    else
        case $OS in
            amzn|amazon)
                dnf install -y git
                ;;
            ubuntu|debian)
                apt install -y git
                ;;
            *)
                dnf install -y git || apt install -y git
                ;;
        esac
    fi
    
    print_success "Git installed: $(git --version)"
}

#===============================================================================
# STEP 4: INSTALL SYSTEM DEPENDENCIES
#===============================================================================

step_4_install_dependencies() {
    print_step "4" "Installing System Dependencies"
    
    case $OS in
        amzn|amazon)
            print_substep "Installing gcc, development tools..."
            dnf groupinstall -y "Development Tools" 2>/dev/null || \
            dnf install -y gcc gcc-c++ make
            dnf install -y libffi-devel openssl-devel
            ;;
        ubuntu|debian)
            print_substep "Installing build-essential..."
            apt install -y build-essential libffi-dev libssl-dev
            ;;
        *)
            print_substep "Installing development tools..."
            dnf install -y gcc make libffi-devel || \
            apt install -y build-essential libffi-dev
            ;;
    esac
    
    print_success "System dependencies installed"
}

#===============================================================================
# STEP 5: SETUP BOT DIRECTORY
#===============================================================================

step_5_setup_directory() {
    print_step "5" "Setting Up Bot Directory"
    
    # Check if we're already in the trading-bot directory
    CURRENT_DIR=$(pwd)
    
    if [[ -f "${CURRENT_DIR}/main.py" ]] && [[ -f "${CURRENT_DIR}/requirements.txt" ]]; then
        print_info "Already in trading-bot directory: ${CURRENT_DIR}"
        BOT_DIR="${CURRENT_DIR}"
        
        # Update the vars file
        echo "BOT_DIR=${BOT_DIR}" >> /tmp/trading_bot_setup_vars
    elif [[ -d "${BOT_DIR}" ]] && [[ -f "${BOT_DIR}/main.py" ]]; then
        print_info "Bot directory already exists: ${BOT_DIR}"
    else
        print_warning "Bot directory not found at ${BOT_DIR}"
        echo ""
        echo -e "${YELLOW}You need to clone your repository first.${NC}"
        echo ""
        echo "Run these commands:"
        echo -e "  ${CYAN}cd /home/${BOT_USER}${NC}"
        echo -e "  ${CYAN}git clone https://github.com/${GITHUB_REPO}.git${NC}"
        echo -e "  ${CYAN}cd trading-bot${NC}"
        echo -e "  ${CYAN}sudo bash deployment/setup.sh${NC}"
        echo ""
        print_error "Please clone the repository and run setup again."
        exit 1
    fi
    
    # Ensure correct ownership
    chown -R ${BOT_USER}:${BOT_GROUP} "${BOT_DIR}"
    
    print_success "Bot directory configured: ${BOT_DIR}"
}

#===============================================================================
# STEP 6: CREATE VIRTUAL ENVIRONMENT
#===============================================================================

step_6_create_venv() {
    print_step "6" "Creating Python Virtual Environment"
    
    # Load Python command
    source /tmp/trading_bot_setup_vars 2>/dev/null || true
    PYTHON_CMD=${PYTHON_CMD:-python3}
    
    cd "${BOT_DIR}"
    
    # Remove old venv if exists (to ensure clean state)
    if [[ -d "venv" ]]; then
        print_info "Removing existing virtual environment..."
        rm -rf venv
    fi
    
    # Create new venv
    print_substep "Creating virtual environment with ${PYTHON_CMD}..."
    sudo -u ${BOT_USER} ${PYTHON_CMD} -m venv venv
    
    # Upgrade pip
    print_substep "Upgrading pip..."
    sudo -u ${BOT_USER} ./venv/bin/pip install --upgrade pip
    
    print_success "Virtual environment created"
}

#===============================================================================
# STEP 7: INSTALL PYTHON PACKAGES
#===============================================================================

step_7_install_packages() {
    print_step "7" "Installing Python Packages"
    
    cd "${BOT_DIR}"
    
    if [[ ! -f "requirements.txt" ]]; then
        print_error "requirements.txt not found!"
        exit 1
    fi
    
    # Install packages
    print_substep "Installing packages from requirements.txt..."
    sudo -u ${BOT_USER} ./venv/bin/pip install -r requirements.txt
    
    # Verify key packages
    print_substep "Verifying package installation..."
    sudo -u ${BOT_USER} ./venv/bin/python -c "
import pandas
import numpy
print('  ✓ pandas', pandas.__version__)
print('  ✓ numpy', numpy.__version__)
try:
    import telegram
    print('  ✓ python-telegram-bot', telegram.__version__)
except ImportError:
    print('  ⚠ python-telegram-bot not installed')
print('All packages OK!')
"
    
    print_success "Python packages installed"
}

#===============================================================================
# STEP 8: SETUP .ENV FILE
#===============================================================================

step_8_setup_env() {
    print_step "8" "Setting Up Environment File"
    
    cd "${BOT_DIR}"
    
    if [[ -f ".env" ]]; then
        print_info ".env file already exists"
        print_warning "Make sure your API keys are configured!"
    elif [[ -f ".env.example" ]]; then
        print_substep "Copying .env.example to .env..."
        sudo -u ${BOT_USER} cp .env.example .env
        
        # Set secure permissions
        chmod 600 .env
        chown ${BOT_USER}:${BOT_GROUP} .env
        
        print_warning "You MUST edit .env with your real API keys!"
        echo ""
        echo -e "  ${CYAN}nano .env${NC}"
        echo ""
    else
        print_warning ".env.example not found. Create .env manually."
    fi
    
    print_success "Environment file configured"
}

#===============================================================================
# STEP 9: CREATE LOGS DIRECTORY
#===============================================================================

step_9_create_logs() {
    print_step "9" "Creating Logs Directory"
    
    cd "${BOT_DIR}"
    
    mkdir -p logs
    chown ${BOT_USER}:${BOT_GROUP} logs
    chmod 755 logs
    
    print_success "Logs directory created: ${BOT_DIR}/logs"
}

#===============================================================================
# STEP 10: SETUP SYSTEMD SERVICE
#===============================================================================

step_10_setup_systemd() {
    print_step "10" "Setting Up Systemd Service"
    
    cd "${BOT_DIR}"
    
    # Check if service file exists in deployment folder
    if [[ -f "deployment/trading-bot.service" ]]; then
        print_substep "Found service file in deployment/"
        SERVICE_SOURCE="deployment/trading-bot.service"
    else
        print_substep "Creating service file..."
        SERVICE_SOURCE="/tmp/trading-bot.service"
        
        cat > ${SERVICE_SOURCE} << EOF
[Unit]
Description=Trading Bot - Options Trading for NSE
After=network.target network-online.target
Wants=network-online.target
Documentation=https://github.com/${GITHUB_REPO}

[Service]
Type=simple
User=${BOT_USER}
Group=${BOT_GROUP}
WorkingDirectory=${BOT_DIR}
ExecStart=${BOT_DIR}/venv/bin/python main.py

# Auto-restart on failure
Restart=always
RestartSec=10

# Environment
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=trading-bot

# Security hardening
ProtectSystem=full
NoNewPrivileges=true
PrivateTmp=true

# Resource limits
MemoryMax=512M
CPUQuota=80%

# Watchdog - restart if unresponsive for 5 minutes
WatchdogSec=300

[Install]
WantedBy=multi-user.target
EOF
    fi
    
    # Copy and update service file
    cp ${SERVICE_SOURCE} /tmp/trading-bot-updated.service
    
    # Replace placeholders with actual values
    sed -i "s|/home/ec2-user/trading-bot|${BOT_DIR}|g" /tmp/trading-bot-updated.service
    sed -i "s|User=ec2-user|User=${BOT_USER}|g" /tmp/trading-bot-updated.service
    sed -i "s|Group=ec2-user|Group=${BOT_GROUP}|g" /tmp/trading-bot-updated.service
    sed -i "s|USERNAME/trading-bot|${GITHUB_REPO}|g" /tmp/trading-bot-updated.service
    
    # Install service
    cp /tmp/trading-bot-updated.service /etc/systemd/system/trading-bot.service
    chmod 644 /etc/systemd/system/trading-bot.service
    
    # Reload systemd
    print_substep "Reloading systemd daemon..."
    systemctl daemon-reload
    
    # Enable service (auto-start on boot)
    print_substep "Enabling service for auto-start..."
    systemctl enable trading-bot
    
    print_success "Systemd service configured"
}

#===============================================================================
# STEP 11: CREATE HELPER SCRIPTS
#===============================================================================

step_11_create_scripts() {
    print_step "11" "Creating Helper Scripts"
    
    cd "${BOT_DIR}"
    
    # start.sh
    print_substep "Creating start.sh..."
    cat > start.sh << 'EOF'
#!/bin/bash
echo "Starting Trading Bot..."
sudo systemctl start trading-bot
sleep 2
if sudo systemctl is-active --quiet trading-bot; then
    echo "✓ Bot started successfully!"
    echo ""
    echo "Check status: ./status.sh"
    echo "View logs:    ./logs.sh"
else
    echo "✗ Bot failed to start. Check logs:"
    echo "  sudo journalctl -u trading-bot -n 50"
fi
EOF

    # stop.sh
    print_substep "Creating stop.sh..."
    cat > stop.sh << 'EOF'
#!/bin/bash
echo "Stopping Trading Bot..."
sudo systemctl stop trading-bot
sleep 1
if ! sudo systemctl is-active --quiet trading-bot; then
    echo "✓ Bot stopped."
else
    echo "⚠ Bot may still be running."
fi
EOF

    # restart.sh
    print_substep "Creating restart.sh..."
    cat > restart.sh << 'EOF'
#!/bin/bash
echo "Restarting Trading Bot..."
sudo systemctl restart trading-bot
sleep 2
if sudo systemctl is-active --quiet trading-bot; then
    echo "✓ Bot restarted successfully!"
else
    echo "✗ Bot failed to restart. Check logs:"
    echo "  sudo journalctl -u trading-bot -n 50"
fi
EOF

    # status.sh
    print_substep "Creating status.sh..."
    cat > status.sh << 'EOF'
#!/bin/bash
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TRADING BOT STATUS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
sudo systemctl status trading-bot --no-pager
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "RECENT LOGS (last 10 lines)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
sudo journalctl -u trading-bot -n 10 --no-pager
EOF

    # logs.sh
    print_substep "Creating logs.sh..."
    cat > logs.sh << 'EOF'
#!/bin/bash
echo "Showing live logs... (Press Ctrl+C to exit)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
sudo journalctl -u trading-bot -f
EOF

    # update.sh
    print_substep "Creating update.sh..."
    cat > update.sh << 'EOF'
#!/bin/bash
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "UPDATING TRADING BOT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Pull latest code
echo ""
echo "→ Pulling latest code from GitHub..."
git pull

# Activate venv and update packages
echo ""
echo "→ Updating Python packages..."
source venv/bin/activate
pip install -r requirements.txt --quiet

# Restart the service
echo ""
echo "→ Restarting bot..."
sudo systemctl restart trading-bot

# Wait and check status
sleep 2
if sudo systemctl is-active --quiet trading-bot; then
    echo ""
    echo "✓ Update complete! Bot is running."
    echo ""
    echo "View logs: ./logs.sh"
else
    echo ""
    echo "✗ Bot failed to start after update. Check logs:"
    echo "  sudo journalctl -u trading-bot -n 50"
fi
EOF

    # backup.sh
    print_substep "Creating backup.sh..."
    cat > backup.sh << 'EOF'
#!/bin/bash
BACKUP_DIR="$HOME/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/trading_bot_backup_${TIMESTAMP}.tar.gz"

mkdir -p ${BACKUP_DIR}

echo "Creating backup..."
tar -czf ${BACKUP_FILE} \
    trading_bot.db \
    .env \
    logs/ \
    2>/dev/null

if [[ -f ${BACKUP_FILE} ]]; then
    echo "✓ Backup created: ${BACKUP_FILE}"
    echo "  Size: $(du -h ${BACKUP_FILE} | cut -f1)"
else
    echo "✗ Backup failed!"
fi
EOF

    # Make all scripts executable
    chmod +x start.sh stop.sh restart.sh status.sh logs.sh update.sh backup.sh
    chown ${BOT_USER}:${BOT_GROUP} start.sh stop.sh restart.sh status.sh logs.sh update.sh backup.sh
    
    print_success "Helper scripts created"
}

#===============================================================================
# STEP 12: PRINT SUMMARY
#===============================================================================

step_12_print_summary() {
    print_step "12" "Setup Complete!"
    
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║${NC}              ${WHITE}${STAR} SETUP COMPLETE! ${STAR}${NC}                            ${GREEN}║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${WHITE}NEXT STEPS:${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    echo -e "${CYAN}1. Edit .env with your API keys:${NC}"
    echo -e "   ${WHITE}cd ${BOT_DIR}${NC}"
    echo -e "   ${WHITE}nano .env${NC}"
    echo ""
    
    echo -e "${CYAN}2. Start the bot:${NC}"
    echo -e "   ${WHITE}./start.sh${NC}"
    echo ""
    
    echo -e "${CYAN}3. Check if running:${NC}"
    echo -e "   ${WHITE}./status.sh${NC}"
    echo ""
    
    echo -e "${CYAN}4. View live logs:${NC}"
    echo -e "   ${WHITE}./logs.sh${NC}"
    echo ""
    
    echo -e "${CYAN}5. Test via Telegram:${NC}"
    echo -e "   Send ${WHITE}/status${NC} to your bot"
    echo ""
    
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${WHITE}HELPER SCRIPTS:${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    echo -e "  ${GREEN}./start.sh${NC}    - Start the bot"
    echo -e "  ${GREEN}./stop.sh${NC}     - Stop the bot"
    echo -e "  ${GREEN}./restart.sh${NC}  - Restart the bot"
    echo -e "  ${GREEN}./status.sh${NC}   - Check bot status"
    echo -e "  ${GREEN}./logs.sh${NC}     - View live logs"
    echo -e "  ${GREEN}./update.sh${NC}   - Pull code + restart"
    echo -e "  ${GREEN}./backup.sh${NC}   - Backup database + .env"
    echo ""
    
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${WHITE}DAILY WORKFLOW:${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    echo -e "  ${BLUE}→${NC} Just use Telegram! Send ${WHITE}/status${NC} to check."
    echo -e "  ${BLUE}→${NC} SSH only needed for updates and debugging."
    echo -e "  ${BLUE}→${NC} Bot auto-restarts on failure and reboot."
    echo ""
    
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${WHITE}USEFUL COMMANDS:${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    echo -e "  View all logs:       ${WHITE}sudo journalctl -u trading-bot${NC}"
    echo -e "  Last 100 lines:      ${WHITE}sudo journalctl -u trading-bot -n 100${NC}"
    echo -e "  Today's logs:        ${WHITE}sudo journalctl -u trading-bot --since today${NC}"
    echo -e "  Memory usage:        ${WHITE}free -h${NC}"
    echo -e "  Disk usage:          ${WHITE}df -h${NC}"
    echo ""
    
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}Happy Trading! 📈${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

#===============================================================================
# MAIN EXECUTION
#===============================================================================

main() {
    print_banner
    
    # Pre-flight checks
    check_root
    detect_os
    detect_user
    
    # Run setup steps
    step_1_system_update
    step_2_install_python
    step_3_install_git
    step_4_install_dependencies
    step_5_setup_directory
    step_6_create_venv
    step_7_install_packages
    step_8_setup_env
    step_9_create_logs
    step_10_setup_systemd
    step_11_create_scripts
    step_12_print_summary
    
    # Cleanup
    rm -f /tmp/trading_bot_setup_vars 2>/dev/null || true
}

# Run main function
main "$@"