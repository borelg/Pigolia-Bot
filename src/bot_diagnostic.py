
#!/usr/bin/env python3
"""
Telegram Bot Diagnostic Tool
============================
Comprehensive diagnostic script to troubleshoot Telegram bot connectivity,
webhook issues, token problems, and basic functionality.

Usage:
    python bot_diagnostic.py YOUR_BOT_TOKEN

Requirements:
    pip install python-telegram-bot httpx requests
"""

import asyncio
import sys
import json
import time
import logging
from datetime import datetime
from typing import Optional, Dict, Any
import traceback

try:
    import httpx
    import requests
    from telegram import Bot, Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.error import TelegramError, NetworkError, BadRequest
except ImportError as e:
    print(f"❌ Missing required packages: {e}")
    print("Install with: pip install python-telegram-bot httpx requests")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_diagnostic.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class TelegramBotDiagnostic:
    def __init__(self, token: str):
        self.token = token
        self.bot = None
        self.application = None
        self.test_results = {}
        
    def log_result(self, test_name: str, success: bool, message: str, details: Optional[Dict] = None):
        """Log test results with timestamp and details"""
        result = {
            'timestamp': datetime.now().isoformat(),
            'success': success,
            'message': message,
            'details': details or {}
        }
        self.test_results[test_name] = result
        
        status = "✅" if success else "❌"
        print(f"\n{status} {test_name}")
        print(f"   {message}")
        if details:
            for key, value in details.items():
                print(f"   {key}: {value}")
        
        logger.info(f"{test_name}: {'SUCCESS' if success else 'FAILED'} - {message}")
        if details:
            logger.debug(f"{test_name} details: {json.dumps(details, indent=2)}")

    def test_token_format(self) -> bool:
        """Test if token has correct format"""
        print("\n🔍 Testing Token Format...")
        
        if not self.token:
            self.log_result("Token Format", False, "Token is empty")
            return False
            
        # Telegram bot tokens should be in format: XXXXXXXXX:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
        parts = self.token.split(':')
        if len(parts) != 2:
            self.log_result("Token Format", False, "Token should contain exactly one colon (:)")
            return False
            
        bot_id, token_part = parts
        
        # Bot ID should be numeric
        if not bot_id.isdigit():
            self.log_result("Token Format", False, "Bot ID part should be numeric")
            return False
            
        # Token part should be 35 characters
        if len(token_part) != 35:
            self.log_result("Token Format", False, f"Token part should be 35 characters, got {len(token_part)}")
            return False
            
        self.log_result("Token Format", True, "Token format appears valid", {
            "bot_id": bot_id,
            "token_length": len(token_part)
        })
        return True

    async def test_basic_connection(self) -> bool:
        """Test basic internet connectivity to Telegram API"""
        print("\n🌐 Testing Basic Connection...")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Test general internet connectivity
                try:
                    response = await client.get("https://httpbin.org/get")
                    if response.status_code != 200:
                        self.log_result("Basic Connection", False, "Cannot reach internet")
                        return False
                except Exception as e:
                    self.log_result("Basic Connection", False, f"Internet connectivity failed: {e}")
                    return False
                
                # Test Telegram API connectivity
                try:
                    response = await client.get("https://api.telegram.org")
                    self.log_result("Basic Connection", True, "Successfully connected to Telegram API", {
                        "status_code": response.status_code,
                        "response_time": f"{response.elapsed.total_seconds():.2f}s"
                    })
                    return True
                except Exception as e:
                    self.log_result("Basic Connection", False, f"Cannot reach Telegram API: {e}")
                    return False
                    
        except Exception as e:
            self.log_result("Basic Connection", False, f"Connection test failed: {e}")
            return False

    async def test_bot_identity(self) -> bool:
        """Test bot token validity and get bot information"""
        print("\n🤖 Testing Bot Identity...")
        
        try:
            self.bot = Bot(token=self.token)
            me = await self.bot.get_me()
            
            self.log_result("Bot Identity", True, f"Bot authenticated successfully: @{me.username}", {
                "id": me.id,
                "first_name": me.first_name,
                "username": me.username,
                "can_join_groups": me.can_join_groups,
                "can_read_all_group_messages": me.can_read_all_group_messages,
                "supports_inline_queries": me.supports_inline_queries
            })
            return True
            
        except BadRequest as e:
            self.log_result("Bot Identity", False, f"Invalid bot token: {e}")
            return False
        except NetworkError as e:
            self.log_result("Bot Identity", False, f"Network error: {e}")
            return False
        except Exception as e:
            self.log_result("Bot Identity", False, f"Authentication failed: {e}")
            return False

    async def test_webhook_status(self) -> bool:
        """Check and clear webhook configuration"""
        print("\n🔗 Testing Webhook Status...")
        
        try:
            webhook_info = await self.bot.get_webhook_info()
            
            if webhook_info.url:
                self.log_result("Webhook Status", False, f"Webhook is set: {webhook_info.url}", {
                    "url": webhook_info.url,
                    "has_custom_certificate": webhook_info.has_custom_certificate,
                    "pending_update_count": webhook_info.pending_update_count,
                    "last_error_date": webhook_info.last_error_date,
                    "last_error_message": webhook_info.last_error_message,
                    "max_connections": webhook_info.max_connections,
                    "allowed_updates": webhook_info.allowed_updates
                })
                
                # Try to clear webhook
                print("   Attempting to clear webhook...")
                try:
                    await self.bot.delete_webhook(drop_pending_updates=True)
                    print("   ✅ Webhook cleared successfully")
                    return True
                except Exception as e:
                    print(f"   ❌ Failed to clear webhook: {e}")
                    return False
            else:
                self.log_result("Webhook Status", True, "No webhook configured (good for polling)")
                return True
                
        except Exception as e:
            self.log_result("Webhook Status", False, f"Failed to check webhook: {e}")
            return False

    async def test_updates_polling(self) -> bool:
        """Test getting updates via polling"""
        print("\n📡 Testing Updates Polling...")
        
        try:
            # Get updates with short polling
            updates = await self.bot.get_updates(timeout=2, limit=1)
            
            self.log_result("Updates Polling", True, f"Polling working, got {len(updates)} updates", {
                "update_count": len(updates),
                "latest_update_id": updates[0].update_id if updates else None
            })
            
            # Clear any pending updates
            if updates:
                last_update_id = updates[-1].update_id
                await self.bot.get_updates(offset=last_update_id + 1, limit=1)
                print(f"   Cleared pending updates up to ID {last_update_id}")
            
            return True
            
        except Exception as e:
            self.log_result("Updates Polling", False, f"Polling failed: {e}")
            return False

    async def test_message_sending(self) -> bool:
        """Test sending a message (requires a chat_id)"""
        print("\n💬 Testing Message Sending...")
        
        # We can't test this without a specific chat_id
        # But we can test the method exists and parameters are correct
        try:
            # This will fail but should give us useful error info
            await self.bot.send_message(chat_id=12345, text="Test message")
        except BadRequest as e:
            if "chat not found" in str(e).lower():
                self.log_result("Message Sending", True, "Message sending capability confirmed (test chat not found is expected)")
                return True
            else:
                self.log_result("Message Sending", False, f"Unexpected error: {e}")
                return False
        except Exception as e:
            self.log_result("Message Sending", False, f"Message sending failed: {e}")
            return False

    async def test_application_setup(self) -> bool:
        """Test Application setup and handler registration"""
        print("\n⚙️ Testing Application Setup...")
        
        try:
            # Create application
            self.application = Application.builder().token(self.token).build()
            
            # Add test handlers
            async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                await update.message.reply_text("Bot is working!")
            
            async def echo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
                await update.message.reply_text(f"Echo: {update.message.text}")
            
            self.application.add_handler(CommandHandler("start", start_handler))
            self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_handler))
            
            # Initialize application
            await self.application.initialize()
            
            self.log_result("Application Setup", True, "Application created and initialized successfully", {
                "handler_count": len(self.application.handlers[0]),  # Default group
                "bot_username": self.application.bot.username if hasattr(self.application.bot, 'username') else None
            })
            return True
            
        except Exception as e:
            self.log_result("Application Setup", False, f"Application setup failed: {e}")
            traceback.print_exc()
            return False

    async def test_concurrent_access(self) -> bool:
        """Test for potential conflicts from multiple bot instances"""
        print("\n🔄 Testing Concurrent Access...")
        
        try:
            # Create multiple bot instances and test them
            bots = [Bot(token=self.token) for _ in range(3)]
            
            # Test all bots can authenticate
            tasks = [bot.get_me() for bot in bots]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            
            if success_count == len(bots):
                self.log_result("Concurrent Access", True, f"All {len(bots)} bot instances authenticated successfully")
                return True
            else:
                self.log_result("Concurrent Access", False, f"Only {success_count}/{len(bots)} instances succeeded", {
                    "errors": [str(r) for r in results if isinstance(r, Exception)]
                })
                return False
                
        except Exception as e:
            self.log_result("Concurrent Access", False, f"Concurrent access test failed: {e}")
            return False

    def test_environment_info(self) -> bool:
        """Gather environment information"""
        print("\n🖥️ Environment Information...")
        
        import platform
        import telegram
        
        try:
            env_info = {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "telegram_lib_version": telegram.__version__,
                "working_directory": os.getcwd() if 'os' in globals() else "unknown",
                "timestamp": datetime.now().isoformat()
            }
            
            self.log_result("Environment Info", True, "Environment information collected", env_info)
            return True
            
        except Exception as e:
            self.log_result("Environment Info", False, f"Failed to collect environment info: {e}")
            return False

    async def run_interactive_test(self) -> bool:
        """Run a brief interactive test if possible"""
        print("\n🎮 Interactive Test...")
        print("This will start the bot for 30 seconds. Send /start to test it.")
        print(f"Find your bot at: https://t.me/{self.application.bot.username}")
        
        try:
            # Start polling for 30 seconds
            async with self.application:
                await self.application.start()
                print("Bot is running... Send /start command to test")
                
                # Run for 30 seconds
                await asyncio.sleep(30)
                
                await self.application.stop()
                
            self.log_result("Interactive Test", True, "Interactive test completed (check logs for user interactions)")
            return True
            
        except KeyboardInterrupt:
            print("\nInteractive test interrupted by user")
            self.log_result("Interactive Test", True, "Interactive test interrupted by user")
            return True
        except Exception as e:
            self.log_result("Interactive Test", False, f"Interactive test failed: {e}")
            return False

    def generate_report(self):
        """Generate comprehensive diagnostic report"""
        print("\n" + "="*60)
        print("📋 DIAGNOSTIC REPORT")
        print("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result['success'])
        
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        print(f"\nDetailed Results:")
        for test_name, result in self.test_results.items():
            status = "✅ PASS" if result['success'] else "❌ FAIL"
            print(f"  {status} | {test_name}: {result['message']}")
        
        # Recommendations
        print(f"\n💡 RECOMMENDATIONS:")
        
        failed_tests = [name for name, result in self.test_results.items() if not result['success']]
        
        if 'Token Format' in failed_tests:
            print("  • Check your bot token format with @BotFather")
        if 'Basic Connection' in failed_tests:
            print("  • Check internet connection and firewall settings")
        if 'Bot Identity' in failed_tests:
            print("  • Verify bot token with @BotFather, create new token if needed")
        if 'Webhook Status' in failed_tests:
            print("  • Clear webhook manually: https://api.telegram.org/bot<TOKEN>/deleteWebhook")
        if 'Updates Polling' in failed_tests:
            print("  • Check if another bot instance is running")
            print("  • Verify network connectivity to api.telegram.org")
        if 'Application Setup' in failed_tests:
            print("  • Check python-telegram-bot library version")
            print("  • Verify code syntax and imports")
        
        if not failed_tests:
            print("  • Your bot appears to be working correctly!")
            print("  • If you're still having issues, check your bot code logic")
            print("  • Enable debug logging to see detailed message flow")
        
        # Save report to file
        with open('diagnostic_report.json', 'w') as f:
            json.dump(self.test_results, f, indent=2)
        
        print(f"\n📄 Full report saved to: diagnostic_report.json")
        print(f"📄 Detailed logs saved to: bot_diagnostic.log")

    async def run_all_tests(self):
        """Run all diagnostic tests"""
        print("🚀 Starting Telegram Bot Diagnostic...")
        print(f"Token: {self.token[:10]}...{self.token[-4:]}")
        
        # Run tests in order
        self.test_token_format()
        await self.test_basic_connection()
        await self.test_bot_identity()
        
        if self.bot:  # Only run if bot was created successfully
            await self.test_webhook_status()
            await self.test_updates_polling()
            await self.test_message_sending()
            await self.test_application_setup()
            await self.test_concurrent_access()
        
        self.test_environment_info()
        
        # Ask user if they want interactive test
        if self.application:
            try:
                response = input("\n❓ Run 30-second interactive test? (y/N): ").strip().lower()
                if response in ['y', 'yes']:
                    await self.run_interactive_test()
            except (KeyboardInterrupt, EOFError):
                print("\nSkipping interactive test")
        
        self.generate_report()

def main():
    if len(sys.argv) != 2:
        print("Usage: python bot_diagnostic.py YOUR_BOT_TOKEN")
        print("Get your token from @BotFather on Telegram")
        sys.exit(1)
    
    token = sys.argv[1].strip()
    
    diagnostic = TelegramBotDiagnostic(token)
    
    try:
        asyncio.run(diagnostic.run_all_tests())
    except KeyboardInterrupt:
        print("\n\n⚠️ Diagnostic interrupted by user")
    except Exception as e:
        print(f"\n\n💥 Diagnostic failed with error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()

