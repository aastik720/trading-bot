#!/usr/bin/env python3
"""
Health Check Script - System Status Verification
==================================================

This standalone script checks the health of all bot components
and can be run independently or scheduled via cron.

Checks Performed:
    1.  Python version >= 3.10
    2.  Required packages installed
    3.  .env file exists with required keys
    4.  Database accessible and tables exist
    5.  Dhan API reachable
    6.  Finnhub API reachable
    7.  Telegram bot token valid
    8.  Disk space > 1GB free
    9.  Memory usage < 80%
    10. Bot process running
    11. Log directory writable
    12. Internet connectivity

Usage:
    # Run manually
    python scripts/health_check.py
    
    # Run as cron job (every hour)
    0 * * * * cd /home/ec2-user/trading-bot && /home/ec2-user/trading-bot/venv/bin/python scripts/health_check.py
    
    # Run with verbose output
    python scripts/health_check.py --verbose
    
    # Run specific checks only
    python scripts/health_check.py --check api
    python scripts/health_check.py --check db
    python scripts/health_check.py --check system

Exit Codes:
    0 - All checks passed
    1 - One or more checks failed

Author: Trading Bot
Phase: 10 - Polish & Enhancement
"""

import os
import sys
import argparse
import socket
import subprocess
import shutil
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ══════════════════════════════════════════════════════════════════════════════
# COLORS AND FORMATTING
# ══════════════════════════════════════════════════════════════════════════════

class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    WHITE = '\033[1;37m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color
    
    @classmethod
    def disable(cls):
        """Disable colors (for non-terminal output)."""
        cls.RED = ''
        cls.GREEN = ''
        cls.YELLOW = ''
        cls.BLUE = ''
        cls.PURPLE = ''
        cls.CYAN = ''
        cls.WHITE = ''
        cls.BOLD = ''
        cls.NC = ''


# Check if output is a terminal
if not sys.stdout.isatty():
    Colors.disable()


def print_header(title: str) -> None:
    """Print a formatted header."""
    print()
    print(f"{Colors.CYAN}{'═' * 50}{Colors.NC}")
    print(f"{Colors.WHITE}{Colors.BOLD}  {title}{Colors.NC}")
    print(f"{Colors.CYAN}{'═' * 50}{Colors.NC}")
    print()


def print_check(name: str, passed: bool, details: str = "", suggestion: str = "") -> None:
    """Print a check result."""
    icon = f"{Colors.GREEN}✅{Colors.NC}" if passed else f"{Colors.RED}❌{Colors.NC}"
    status = f"{Colors.GREEN}OK{Colors.NC}" if passed else f"{Colors.RED}FAILED{Colors.NC}"
    
    # Fixed width name for alignment
    name_padded = f"{name}:".ljust(14)
    
    print(f"  {icon} {name_padded} {details}")
    
    if not passed and suggestion:
        print(f"     {Colors.YELLOW}→ {suggestion}{Colors.NC}")


def print_warning(message: str) -> None:
    """Print a warning message."""
    print(f"  {Colors.YELLOW}⚠️  {message}{Colors.NC}")


def print_info(message: str) -> None:
    """Print an info message."""
    print(f"  {Colors.BLUE}ℹ️  {message}{Colors.NC}")


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK CLASS
# ══════════════════════════════════════════════════════════════════════════════

class HealthChecker:
    """
    Performs comprehensive health checks on the trading bot system.
    
    Attributes:
        verbose: Whether to show detailed output
        results: Dict of check results
        
    Example:
        >>> checker = HealthChecker(verbose=True)
        >>> all_passed = checker.run_all_checks()
        >>> sys.exit(0 if all_passed else 1)
    """
    
    # Minimum requirements
    MIN_PYTHON_VERSION = (3, 10)
    MIN_DISK_SPACE_GB = 1
    MAX_MEMORY_USAGE_PCT = 80
    
    # Required packages to check
    REQUIRED_PACKAGES = [
        "pandas",
        "numpy",
        "requests",
        "sqlalchemy",
        "python-telegram-bot",
        "python-dotenv",
    ]
    
    # Required .env keys
    REQUIRED_ENV_KEYS = [
        "PAPER_TRADING",
        "INITIAL_CAPITAL",
        "DHAN_CLIENT_ID",
        "DHAN_ACCESS_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]
    
    # Optional .env keys
    OPTIONAL_ENV_KEYS = [
        "FINNHUB_API_KEY",
        "TELEGRAM_ADMIN_IDS",
    ]
    
    def __init__(self, verbose: bool = False):
        """
        Initialize health checker.
        
        Args:
            verbose: Whether to show detailed output
        """
        self.verbose = verbose
        self.results: Dict[str, Tuple[bool, str, str]] = {}
        self.start_time = datetime.now()
    
    def run_all_checks(self) -> bool:
        """
        Run all health checks.
        
        Returns:
            True if all checks passed, False otherwise
        """
        print_header(f"HEALTH CHECK - {self.start_time.strftime('%d %b %Y %H:%M')}")
        
        # Run all checks
        self.check_python_version()
        self.check_packages()
        self.check_env_file()
        self.check_database()
        self.check_dhan_api()
        self.check_finnhub_api()
        self.check_telegram()
        self.check_disk_space()
        self.check_memory()
        self.check_bot_process()
        self.check_logs_directory()
        self.check_internet()
        
        # Print summary
        return self.print_summary()
    
    def run_specific_checks(self, category: str) -> bool:
        """
        Run specific category of checks.
        
        Args:
            category: 'api', 'db', 'system', or 'config'
            
        Returns:
            True if all checks in category passed
        """
        print_header(f"HEALTH CHECK ({category.upper()}) - {self.start_time.strftime('%H:%M')}")
        
        if category == 'api':
            self.check_dhan_api()
            self.check_finnhub_api()
            self.check_telegram()
            self.check_internet()
        elif category == 'db':
            self.check_database()
        elif category == 'system':
            self.check_python_version()
            self.check_disk_space()
            self.check_memory()
            self.check_bot_process()
        elif category == 'config':
            self.check_env_file()
            self.check_packages()
            self.check_logs_directory()
        else:
            print(f"Unknown category: {category}")
            print("Available: api, db, system, config")
            return False
        
        return self.print_summary()
    
    # ══════════════════════════════════════════════════════════════════════════
    # INDIVIDUAL CHECKS
    # ══════════════════════════════════════════════════════════════════════════
    
    def check_python_version(self) -> None:
        """Check Python version meets requirements."""
        check_name = "Python"
        
        try:
            version = sys.version_info
            version_str = f"{version.major}.{version.minor}.{version.micro}"
            
            passed = version >= self.MIN_PYTHON_VERSION
            details = version_str
            suggestion = f"Upgrade to Python {self.MIN_PYTHON_VERSION[0]}.{self.MIN_PYTHON_VERSION[1]}+"
            
            self.results[check_name] = (passed, details, suggestion)
            print_check(check_name, passed, details, "" if passed else suggestion)
            
        except Exception as e:
            self.results[check_name] = (False, str(e), "Check Python installation")
            print_check(check_name, False, str(e), "Check Python installation")
    
    def check_packages(self) -> None:
        """Check all required packages are installed."""
        check_name = "Packages"
        
        missing = []
        installed_count = 0
        
        for package in self.REQUIRED_PACKAGES:
            try:
                # Handle package name differences
                import_name = package.replace("-", "_")
                if package == "python-telegram-bot":
                    import_name = "telegram"
                elif package == "python-dotenv":
                    import_name = "dotenv"
                
                __import__(import_name)
                installed_count += 1
            except ImportError:
                missing.append(package)
        
        passed = len(missing) == 0
        details = f"All {installed_count} installed" if passed else f"Missing: {', '.join(missing)}"
        suggestion = f"pip install {' '.join(missing)}"
        
        self.results[check_name] = (passed, details, suggestion)
        print_check(check_name, passed, details, "" if passed else suggestion)
        
        if self.verbose and passed:
            for pkg in self.REQUIRED_PACKAGES:
                print(f"       ✓ {pkg}")
    
    def check_env_file(self) -> None:
        """Check .env file exists and has required keys."""
        check_name = ".env"
        
        env_path = PROJECT_ROOT / ".env"
        
        if not env_path.exists():
            self.results[check_name] = (False, "File not found", "Copy .env.example to .env")
            print_check(check_name, False, "File not found", "Copy .env.example to .env")
            return
        
        # Load and check keys
        try:
            from dotenv import dotenv_values
            env_values = dotenv_values(env_path)
        except ImportError:
            # Fallback: manual parsing
            env_values = {}
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key = line.split('=')[0].strip()
                        env_values[key] = True
        
        # Check required keys
        missing_required = []
        for key in self.REQUIRED_ENV_KEYS:
            if key not in env_values:
                missing_required.append(key)
        
        # Check optional keys
        missing_optional = []
        for key in self.OPTIONAL_ENV_KEYS:
            if key not in env_values:
                missing_optional.append(key)
        
        total_keys = len(env_values)
        
        if missing_required:
            passed = False
            details = f"Missing: {', '.join(missing_required)}"
            suggestion = f"Add missing keys to .env"
        else:
            passed = True
            details = f"Found ({total_keys} keys)"
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
        
        if missing_optional and self.verbose:
            print_warning(f"Optional keys missing: {', '.join(missing_optional)}")
    
    def check_database(self) -> None:
        """Check database is accessible and has tables."""
        check_name = "Database"
        
        try:
            from database import get_database_manager, get_trade_repo
            
            db = get_database_manager()
            trade_repo = get_trade_repo()
            
            # Try to get stats
            stats = trade_repo.get_stats()
            total_trades = stats.get("total_trades", 0)
            
            passed = True
            details = f"OK ({total_trades} trades)"
            suggestion = ""
            
        except ImportError as e:
            passed = False
            details = "Module not found"
            suggestion = "Check database module exists"
        except Exception as e:
            passed = False
            details = str(e)[:30]
            suggestion = "Run: python -c 'from database import get_database_manager; get_database_manager().create_tables()'"
        
        self.results[check_name] = (passed, details, suggestion)
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    def check_dhan_api(self) -> None:
        """Check Dhan API is reachable."""
        check_name = "Dhan API"
        
        try:
            import requests
            
            # Try to reach Dhan API
            response = requests.get(
                "https://api.dhan.co/",
                timeout=10
            )
            
            if response.status_code in [200, 401, 403]:
                # 401/403 means API is reachable but auth required
                passed = True
                details = "Connected"
            else:
                passed = False
                details = f"Status: {response.status_code}"
            
            suggestion = "Check DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN"
            
        except requests.exceptions.Timeout:
            passed = False
            details = "Timeout"
            suggestion = "Check internet connection"
        except requests.exceptions.ConnectionError:
            passed = False
            details = "Connection failed"
            suggestion = "Check internet connection"
        except Exception as e:
            passed = False
            details = str(e)[:30]
            suggestion = "Check Dhan API status"
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    def check_finnhub_api(self) -> None:
        """Check Finnhub API is reachable."""
        check_name = "Finnhub API"
        
        try:
            import requests
            
            # Check if API key is configured
            api_key = os.environ.get("FINNHUB_API_KEY", "")
            
            if not api_key:
                # Try loading from .env
                try:
                    from dotenv import load_dotenv
                    load_dotenv(PROJECT_ROOT / ".env")
                    api_key = os.environ.get("FINNHUB_API_KEY", "")
                except ImportError:
                    pass
            
            if not api_key:
                passed = True  # Optional, so mark as OK
                details = "Not configured (optional)"
                suggestion = ""
            else:
                # Try API call
                response = requests.get(
                    f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={api_key}",
                    timeout=10
                )
                
                if response.status_code == 200:
                    passed = True
                    details = "Connected"
                elif response.status_code == 401:
                    passed = False
                    details = "Invalid API key"
                    suggestion = "Check FINNHUB_API_KEY in .env"
                else:
                    passed = False
                    details = f"Status: {response.status_code}"
                    suggestion = "Check Finnhub API status"
            
        except requests.exceptions.Timeout:
            passed = False
            details = "Timeout"
            suggestion = "Check internet connection"
        except Exception as e:
            passed = False
            details = str(e)[:30]
            suggestion = "Check Finnhub configuration"
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    def check_telegram(self) -> None:
        """Check Telegram bot token is valid."""
        check_name = "Telegram"
        
        try:
            import requests
            
            # Get token from environment or .env
            token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            
            if not token:
                try:
                    from dotenv import load_dotenv
                    load_dotenv(PROJECT_ROOT / ".env")
                    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                except ImportError:
                    pass
            
            if not token:
                passed = False
                details = "Token not found"
                suggestion = "Set TELEGRAM_BOT_TOKEN in .env"
            else:
                # Call getMe API
                response = requests.get(
                    f"https://api.telegram.org/bot{token}/getMe",
                    timeout=10
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        bot_username = data.get("result", {}).get("username", "unknown")
                        passed = True
                        details = f"@{bot_username}"
                    else:
                        passed = False
                        details = "Invalid response"
                        suggestion = "Check bot token"
                elif response.status_code == 401:
                    passed = False
                    details = "Invalid token"
                    suggestion = "Get new token from @BotFather"
                else:
                    passed = False
                    details = f"Status: {response.status_code}"
                    suggestion = "Check Telegram API status"
            
        except requests.exceptions.Timeout:
            passed = False
            details = "Timeout"
            suggestion = "Check internet connection"
        except Exception as e:
            passed = False
            details = str(e)[:30]
            suggestion = "Check Telegram configuration"
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    def check_disk_space(self) -> None:
        """Check available disk space."""
        check_name = "Disk"
        
        try:
            total, used, free = shutil.disk_usage(PROJECT_ROOT)
            
            free_gb = free / (1024 ** 3)
            total_gb = total / (1024 ** 3)
            used_pct = (used / total) * 100
            
            passed = free_gb >= self.MIN_DISK_SPACE_GB
            details = f"{free_gb:.1f} GB free"
            suggestion = "Free up disk space"
            
            if self.verbose:
                print_info(f"Total: {total_gb:.1f} GB, Used: {used_pct:.1f}%")
            
        except Exception as e:
            passed = False
            details = str(e)[:30]
            suggestion = "Check disk access"
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    def check_memory(self) -> None:
        """Check memory usage."""
        check_name = "Memory"
        
        try:
            import psutil
            
            memory = psutil.virtual_memory()
            used_mb = memory.used / (1024 ** 2)
            total_mb = memory.total / (1024 ** 2)
            used_pct = memory.percent
            
            passed = used_pct < self.MAX_MEMORY_USAGE_PCT
            details = f"{used_mb:.0f} MB / {total_mb:.0f} MB ({used_pct:.0f}%)"
            suggestion = "Close other applications or upgrade instance"
            
        except ImportError:
            # psutil not installed, try alternative
            try:
                with open('/proc/meminfo', 'r') as f:
                    lines = f.readlines()
                
                mem_total = 0
                mem_available = 0
                
                for line in lines:
                    if line.startswith('MemTotal:'):
                        mem_total = int(line.split()[1]) / 1024  # MB
                    elif line.startswith('MemAvailable:'):
                        mem_available = int(line.split()[1]) / 1024  # MB
                
                if mem_total > 0:
                    used_mb = mem_total - mem_available
                    used_pct = (used_mb / mem_total) * 100
                    
                    passed = used_pct < self.MAX_MEMORY_USAGE_PCT
                    details = f"{used_mb:.0f} MB / {mem_total:.0f} MB ({used_pct:.0f}%)"
                else:
                    passed = True
                    details = "N/A (install psutil for details)"
                    
            except Exception:
                passed = True
                details = "N/A (install psutil)"
            
            suggestion = "pip install psutil"
            
        except Exception as e:
            passed = True
            details = f"N/A ({str(e)[:20]})"
            suggestion = ""
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    def check_bot_process(self) -> None:
        """Check if trading bot process is running."""
        check_name = "Bot Process"
        
        try:
            # Check systemd service status
            result = subprocess.run(
                ["systemctl", "is-active", "trading-bot"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            status = result.stdout.strip()
            
            if status == "active":
                # Get uptime
                uptime_result = subprocess.run(
                    ["systemctl", "show", "trading-bot", "--property=ActiveEnterTimestamp"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                uptime_str = ""
                if uptime_result.returncode == 0:
                    timestamp_str = uptime_result.stdout.strip().split("=")[1]
                    if timestamp_str:
                        try:
                            # Parse systemd timestamp
                            start_time = datetime.strptime(
                                timestamp_str.split(".")[0],
                                "%a %Y-%m-%d %H:%M:%S"
                            )
                            uptime = datetime.now() - start_time
                            days = uptime.days
                            hours = uptime.seconds // 3600
                            mins = (uptime.seconds % 3600) // 60
                            
                            if days > 0:
                                uptime_str = f" (uptime: {days}d {hours}h)"
                            else:
                                uptime_str = f" (uptime: {hours}h {mins}m)"
                        except Exception:
                            pass
                
                passed = True
                details = f"Running{uptime_str}"
            else:
                passed = False
                details = f"Status: {status}"
            
            suggestion = "sudo systemctl start trading-bot"
            
        except FileNotFoundError:
            # systemctl not available (not Linux or not installed)
            try:
                import psutil
                
                # Look for python process running main.py
                bot_running = False
                for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                    try:
                        cmdline = proc.info['cmdline']
                        if cmdline and 'main.py' in ' '.join(cmdline):
                            bot_running = True
                            break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                
                passed = bot_running
                details = "Running" if bot_running else "Not running"
                suggestion = "python main.py"
                
            except ImportError:
                passed = True  # Can't check, assume OK
                details = "N/A (not on Linux)"
                suggestion = ""
                
        except subprocess.TimeoutExpired:
            passed = True
            details = "N/A (timeout)"
            suggestion = ""
        except Exception as e:
            passed = True
            details = f"N/A ({str(e)[:20]})"
            suggestion = ""
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    def check_logs_directory(self) -> None:
        """Check logs directory exists and is writable."""
        check_name = "Logs"
        
        logs_dir = PROJECT_ROOT / "logs"
        
        try:
            # Create if doesn't exist
            if not logs_dir.exists():
                logs_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if writable
            test_file = logs_dir / ".write_test"
            try:
                test_file.write_text("test")
                test_file.unlink()
                passed = True
                details = "Writable"
            except Exception:
                passed = False
                details = "Not writable"
                suggestion = f"chmod 755 {logs_dir}"
            
        except Exception as e:
            passed = False
            details = str(e)[:30]
            suggestion = f"mkdir -p {logs_dir}"
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    def check_internet(self) -> None:
        """Check internet connectivity."""
        check_name = "Internet"
        
        try:
            # Try to connect to Google DNS
            socket.create_connection(("8.8.8.8", 53), timeout=5)
            passed = True
            details = "Connected"
            suggestion = ""
        except socket.timeout:
            passed = False
            details = "Timeout"
            suggestion = "Check network connection"
        except socket.error:
            passed = False
            details = "No connection"
            suggestion = "Check network configuration"
        except Exception as e:
            passed = False
            details = str(e)[:30]
            suggestion = "Check network"
        
        self.results[check_name] = (passed, details, suggestion if not passed else "")
        print_check(check_name, passed, details, "" if passed else suggestion)
    
    # ══════════════════════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════════════════════
    
    def print_summary(self) -> bool:
        """
        Print summary of all checks.
        
        Returns:
            True if all checks passed
        """
        print()
        
        passed_count = sum(1 for passed, _, _ in self.results.values() if passed)
        total_count = len(self.results)
        failed_count = total_count - passed_count
        
        if failed_count == 0:
            print(f"{Colors.GREEN}{'═' * 50}{Colors.NC}")
            print(f"{Colors.GREEN}  STATUS: ALL SYSTEMS GO ✅{Colors.NC}")
            print(f"{Colors.GREEN}  {passed_count}/{total_count} checks passed{Colors.NC}")
            print(f"{Colors.GREEN}{'═' * 50}{Colors.NC}")
            return True
        else:
            print(f"{Colors.RED}{'═' * 50}{Colors.NC}")
            print(f"{Colors.RED}  STATUS: ISSUES DETECTED ❌{Colors.NC}")
            print(f"{Colors.RED}  {passed_count}/{total_count} checks passed, {failed_count} failed{Colors.NC}")
            print(f"{Colors.RED}{'═' * 50}{Colors.NC}")
            
            print()
            print(f"{Colors.YELLOW}  Failed checks:{Colors.NC}")
            for name, (passed, details, suggestion) in self.results.items():
                if not passed:
                    print(f"    • {name}: {details}")
                    if suggestion:
                        print(f"      Fix: {suggestion}")
            
            return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Trading Bot Health Check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/health_check.py              # Run all checks
  python scripts/health_check.py --verbose    # Detailed output
  python scripts/health_check.py --check api  # Check APIs only
  python scripts/health_check.py --check db   # Check database only
        """
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output"
    )
    
    parser.add_argument(
        "-c", "--check",
        choices=["api", "db", "system", "config", "all"],
        default="all",
        help="Run specific category of checks"
    )
    
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable colored output"
    )
    
    args = parser.parse_args()
    
    if args.no_color:
        Colors.disable()
    
    # Change to project root
    os.chdir(PROJECT_ROOT)
    
    # Load environment variables
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Run checks
    checker = HealthChecker(verbose=args.verbose)
    
    if args.check == "all":
        all_passed = checker.run_all_checks()
    else:
        all_passed = checker.run_specific_checks(args.check)
    
    print()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()