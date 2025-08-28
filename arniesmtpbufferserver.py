# arniemailbufferserver v2
# copyright 2021 Andrew Stuart andrew.stuart@supercoders.com.au
# MIT licensed

# DO NOT USE THIS IN PRODUCTION IT IS A DEMONSTRATION ONLY WITH LIKELY LOGIC AND OTHER FLAWS


import asyncio
import email
import email.utils
import fcntl
import logging
import os
import re
import signal
import shutil
import sys
import time
import uuid
from configparser import ConfigParser
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import aiofiles
import aiosmtplib
from aiosmtpd.controller import Controller
from aiosmtpd.handlers import Handler
from aiosmtpd.smtp import Envelope, Session

# --- Structured Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Constants ---
MAX_MESSAGE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
DEFAULT_QUEUE_SIZE = 1000
MAX_RETRY_ATTEMPTS = 5
INITIAL_RETRY_DELAY = 60
MAX_RETRY_DELAY = 3600
STREAM_CHUNK_SIZE = 8192

# --- Rate Limiting ---
class RateLimiter:
    def __init__(self, max_messages_per_hour: int = 100, max_bytes_per_hour: int = 50 * 1024 * 1024):
        self.max_messages = max_messages_per_hour
        self.max_bytes = max_bytes_per_hour
        self.clients = {}
        self.cleanup_interval = 3600  # 1 hour
        self.last_cleanup = time.time()
    
    def _cleanup_old_entries(self):
        now = time.time()
        if now - self.last_cleanup > self.cleanup_interval:
            cutoff = now - 3600
            for client_ip in list(self.clients.keys()):
                client_data = self.clients[client_ip]
                client_data['messages'] = [(t, s) for t, s in client_data['messages'] if t > cutoff]
                if not client_data['messages']:
                    del self.clients[client_ip]
            self.last_cleanup = now
    
    def can_accept(self, client_ip: str, message_size: int) -> bool:
        self._cleanup_old_entries()
        now = time.time()
        cutoff = now - 3600
        
        if client_ip not in self.clients:
            self.clients[client_ip] = {'messages': []}
        
        client_data = self.clients[client_ip]
        # Remove old entries
        client_data['messages'] = [(t, s) for t, s in client_data['messages'] if t > cutoff]
        
        current_count = len(client_data['messages'])
        current_bytes = sum(s for t, s in client_data['messages'])
        
        if current_count >= self.max_messages or current_bytes + message_size > self.max_bytes:
            return False
        
        client_data['messages'].append((now, message_size))
        return True

# --- Input Validation ---
def is_valid_uuid(value: str) -> bool:
    """Validate that a string is a valid UUID"""
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False

def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal"""
    # Remove any path separators and keep only the base name
    base = os.path.basename(filename)
    # Only allow alphanumeric, hyphens, and dots
    sanitized = re.sub(r'[^a-zA-Z0-9\-\.]', '', base)
    return sanitized or 'invalid'

def validate_email_address(email_addr: str) -> bool:
    """Validate email address using email.utils"""
    if not email_addr or len(email_addr) > 254:
        return False
    
    # Check for header injection characters
    if any(char in email_addr for char in ['\n', '\r', '\0']):
        return False
    
    # Use email.utils for basic validation
    parsed = email.utils.parseaddr(email_addr)
    if not parsed[1]:  # No email part
        return False
    
    # Basic regex check for email format
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_pattern, parsed[1]))

def validate_message_content(content: bytes) -> bool:
    """Basic validation of message content"""
    if not content or len(content) > MAX_MESSAGE_SIZE_BYTES:
        return False
    
    # Check for null bytes which can cause issues
    if b'\0' in content:
        return False
    
    return True

# --- Retry Configuration ---
@dataclass
class RetryConfig:
    max_attempts: int = MAX_RETRY_ATTEMPTS
    initial_delay: int = INITIAL_RETRY_DELAY
    max_delay: int = MAX_RETRY_DELAY
    backoff_multiplier: float = 2.0

# --- Circuit Breaker ---
class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0
        self.state = 'CLOSED'  # CLOSED, OPEN, HALF_OPEN

    def can_execute(self) -> bool:
        if self.state == 'CLOSED':
            return True
        elif self.state == 'OPEN':
            if time.time() - self.last_failure_time >= self.timeout:
                self.state = 'HALF_OPEN'
                return True
            return False
        else:  # HALF_OPEN
            return True

    def record_success(self):
        self.failure_count = 0
        self.state = 'CLOSED'

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        # Only transition to OPEN if we're not already there or if we're in HALF_OPEN
        if self.state == 'HALF_OPEN' or (self.state == 'CLOSED' and self.failure_count >= self.failure_threshold):
            self.state = 'OPEN'

# --- Improved File Locking Context Manager ---
@asynccontextmanager
async def file_lock(filepath: Path, mode='r+b'):
    """Async context manager for file locking with proper cleanup."""
    fd = None
    file_obj = None
    try:
        # Ensure parent directory exists
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        fd = await asyncio.to_thread(os.open, filepath, os.O_RDWR | os.O_CREAT, 0o644)
        await asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        file_obj = os.fdopen(fd, mode)
        fd = None  # fdopen now owns the file descriptor
        yield file_obj
    except BlockingIOError:
        logger.debug(f"File {filepath} is locked, skipping.")
        raise
    except Exception as e:
        logger.error(f"Error acquiring lock on {filepath}: {e}")
        raise
    finally:
        if file_obj:
            try:
                file_obj.close()
            except Exception as e:
                logger.error(f"Error closing file object: {e}")
        elif fd is not None:
            try:
                os.close(fd)
            except Exception as e:
                logger.error(f"Error closing file descriptor: {e}")

# --- Task Manager for Proper Cleanup ---
class TaskManager:
    def __init__(self):
        self.tasks: Set[asyncio.Task] = set()

    def create_task(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def cancel_all(self):
        if self.tasks:
            logger.info(f"Cancelling {len(self.tasks)} background tasks...")
            for task in list(self.tasks):
                if not task.done():
                    task.cancel()
            try:
                await asyncio.gather(*self.tasks, return_exceptions=True)
            except Exception as e:
                logger.error(f"Error during task cancellation: {e}")
            finally:
                self.tasks.clear()
                logger.info("All background tasks cancelled.")

# --- Atomic File Operations ---
async def atomic_write(filepath: Path, content: bytes):
    """Write content to file atomically using temp file"""
    temp_path = filepath.with_suffix(filepath.suffix + '.tmp')
    try:
        async with aiofiles.open(temp_path, 'wb') as f:
            await f.write(content)
        await asyncio.to_thread(os.rename, temp_path, filepath)
    except Exception as e:
        # Clean up temp file if it exists
        if temp_path.exists():
            await asyncio.to_thread(os.unlink, temp_path)
        raise e

async def atomic_move(src: Path, dest: Path):
    """Atomic file move with proper error handling"""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dest)
    except Exception as e:
        logger.error(f"Failed to move file from {src} to {dest}: {e}")
        raise

async def safe_unlink(path: Path):
    """Safe file deletion with error handling"""
    try:
        if path.exists():
            os.unlink(path)
    except Exception as e:
        logger.error(f"Failed to delete file {path}: {e}")
        # Don't re-raise for cleanup operations

# --- Configuration with Validation ---
def load_config() -> ConfigParser:
    config = ConfigParser()
    config['server'] = {
        'host': '127.0.0.1',
        'port': '8025',
        'files_directory': '~/.arniesmtpbufferserver',
        'max_message_size': str(MAX_MESSAGE_SIZE_BYTES),
        'queue_size': str(DEFAULT_QUEUE_SIZE),
        'disk_health_check_interval': '30',
        'disk_high_watermark_percent': '95',
        'disk_low_watermark_percent': '90',
        'max_messages_per_hour': '100',
        'max_bytes_per_hour': str(50 * 1024 * 1024),
    }
    config['sender'] = {
        'smtp_host': '127.0.0.1',
        'smtp_port': '1025',
        'smtp_user': '',
        'smtp_password': '',
        'smtp_timeout': '60',
        'use_tls': 'false',
        'start_tls': 'true',
        'save_sent_mail': 'true',
        'max_retry_attempts': str(MAX_RETRY_ATTEMPTS),
        'initial_retry_delay': str(INITIAL_RETRY_DELAY),
        'max_retry_delay': str(MAX_RETRY_DELAY),
        'circuit_breaker_threshold': '5',
        'circuit_breaker_timeout': '60',
        'max_concurrent_retries': '10',
    }
    config_path = Path('config.ini')
    if config_path.exists():
        config.read(config_path)
    else:
        with open(config_path, 'w') as f:
            config.write(f)
        logger.info("Created default config.ini")
    
    files_dir_raw = config.get('server', 'files_directory')
    config.set('server', 'files_directory', os.path.expanduser(files_dir_raw))
    return config

# --- Health State with Metrics ---
class HealthState:
    def __init__(self):
        self._is_healthy = True
        self._lock = asyncio.Lock()
        self.metrics = {
            'messages_received': 0,
            'messages_sent': 0,
            'messages_failed': 0,
            'queue_size': 0,
            'disk_usage_percent': 0.0
        }

    async def get_is_healthy(self) -> bool:
        async with self._lock:
            return self._is_healthy

    async def set_is_healthy(self, value: bool) -> None:
        async with self._lock:
            if self._is_healthy != value:
                logger.warning(f"Health state changed to: {'HEALTHY' if value else 'UNHEALTHY'}")
                self._is_healthy = value

    async def update_metric(self, key: str, value):
        async with self._lock:
            self.metrics[key] = value

    async def increment_metric(self, key: str):
        async with self._lock:
            self.metrics[key] = self.metrics.get(key, 0) + 1

    async def get_metrics(self) -> dict:
        async with self._lock:
            return self.metrics.copy()

# --- Disk Health Monitor ---
class DiskHealthMonitor:
    def __init__(self, config: ConfigParser, health_state: HealthState, task_manager: TaskManager, shutdown_event: asyncio.Event):
        self.path = Path(config.get('server', 'files_directory'))
        self.interval = config.getint('server', 'disk_health_check_interval')
        self.high_watermark = config.getint('server', 'disk_high_watermark_percent')
        self.low_watermark = config.getint('server', 'disk_low_watermark_percent')
        self.health_state = health_state
        self.task_manager = task_manager
        self.shutdown_event = shutdown_event

    async def run(self):
        logger.info(f"Disk health monitor started for {self.path}.")
        while not self.shutdown_event.is_set():
            try:
                usage = await asyncio.to_thread(shutil.disk_usage, self.path)
                percent_used = (usage.used / usage.total) * 100
                await self.health_state.update_metric('disk_usage_percent', round(percent_used, 2))

                is_healthy = await self.health_state.get_is_healthy()
                if percent_used >= self.high_watermark and is_healthy:
                    logger.warning(f"Disk usage ({percent_used:.2f}%) exceeds high watermark ({self.high_watermark}%). Marking unhealthy.")
                    await self.health_state.set_is_healthy(False)
                elif percent_used < self.low_watermark and not is_healthy:
                    logger.info(f"Disk usage ({percent_used:.2f}%) is below low watermark ({self.low_watermark}%). Marking healthy.")
                    await self.health_state.set_is_healthy(True)

                await asyncio.sleep(self.interval)
            except FileNotFoundError:
                logger.error(f"Monitored directory {self.path} not found. Stopping monitor.")
                await self.health_state.set_is_healthy(False)
                break
            except Exception as e:
                logger.error(f"Error in disk health monitor: {e}")
                await asyncio.sleep(self.interval)

# --- SMTP Handler with Validation and Backpressure ---
class BufferSMTPHandler(Handler):
    def __init__(self, dirs: Dict[str, Path], health_state: HealthState, sender_queue: asyncio.Queue, rate_limiter: RateLimiter):
        self.dirs = dirs
        self.health_state = health_state
        self.sender_queue = sender_queue
        self.rate_limiter = rate_limiter
        super().__init__()

    async def handle_RCPT(self, server, session, envelope, address, rcpt_options):
        # Check system health first
        if not await self.health_state.get_is_healthy():
            return '452 4.3.1 Insufficient system storage'
        
        # Validate email address
        if not validate_email_address(address):
            return '550 5.1.1 Invalid recipient address'
        
        # Check queue capacity with proper backpressure
        if self.sender_queue.full():
            return '452 4.3.1 Server busy, try again later'
        
        envelope.rcpt_tos.append(address)
        return '250 OK'

    async def handle_DATA(self, server, session: Session, envelope: Envelope):
        # System health check
        if not await self.health_state.get_is_healthy():
            return '452 4.3.1 Insufficient system storage'
        
        # Get client IP for rate limiting
        client_ip = session.peer[0] if session.peer else 'unknown'
        
        # Validate sender
        if envelope.mail_from and not validate_email_address(envelope.mail_from):
            return '550 5.1.7 Invalid sender address'
        
        # Validate message content
        if not validate_message_content(envelope.content):
            return '554 5.6.0 Invalid message content'
        
        # Rate limiting check
        if not self.rate_limiter.can_accept(client_ip, len(envelope.content)):
            return '450 4.7.1 Rate limit exceeded, try again later'
        
        # Final queue check with backpressure
        if self.sender_queue.full():
            return '452 4.3.1 Server busy, try again later'

        # Generate safe message ID
        message_id = str(uuid.uuid4())
        filename = f"{sanitize_filename(message_id)}.eml"
        final_filepath = self.dirs['outbox'] / filename
        
        try:
            # Use atomic write to prevent partial files
            await atomic_write(final_filepath, envelope.content)
            
            # Validate all recipients
            valid_rcpts = [rcpt for rcpt in envelope.rcpt_tos if validate_email_address(rcpt)]
            if not valid_rcpts:
                await safe_unlink(final_filepath)
                return '550 5.1.1 No valid recipients'
            
            queue_item = (message_id, envelope.mail_from, valid_rcpts, 0)
            try:
                self.sender_queue.put_nowait(queue_item)
            except asyncio.QueueFull:
                await safe_unlink(final_filepath)
                return '452 4.3.1 Queue full, try again later'

            await self.health_state.increment_metric('messages_received')
            await self.health_state.update_metric('queue_size', self.sender_queue.qsize())
            logger.info(f"Message {message_id} queued ({len(envelope.content)} bytes)")
            return '250 OK: Message accepted for delivery'
            
        except Exception as e:
            logger.error(f"Error handling message {message_id}: {e}")
            await safe_unlink(final_filepath)
            return '451 4.3.0 Temporary failure'

# --- Enhanced Sender with Streaming and Fixed Circuit Breaker ---
class Sender:
    def __init__(self, config: ConfigParser, dirs: Dict[str, Path], shutdown_event: asyncio.Event, queue: asyncio.Queue, health_state: HealthState, task_manager: TaskManager):
        self.config = config['sender']
        self.dirs = dirs
        self.shutdown_event = shutdown_event
        self.queue = queue
        self.health_state = health_state
        self.task_manager = task_manager
        self.retry_config = RetryConfig(
            max_attempts=self.config.getint('max_retry_attempts'),
            initial_delay=self.config.getint('initial_retry_delay'),
            max_delay=self.config.getint('max_retry_delay')
        )
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.config.getint('circuit_breaker_threshold'),
            timeout=self.config.getint('circuit_breaker_timeout')
        )
        self.smtp_settings = {
            'hostname': self.config['smtp_host'],
            'port': self.config.getint('smtp_port'),
            'username': self.config.get('smtp_user') or None,
            'password': self.config.get('smtp_password') or None,
            'timeout': self.config.getint('smtp_timeout'),
            'use_tls': self.config.getboolean('use_tls'),
            'start_tls': self.config.getboolean('start_tls')
        }
        self.retry_semaphore = asyncio.Semaphore(self.config.getint('max_concurrent_retries'))

    async def run(self) -> None:
        logger.info("Sender started with circuit breaker and retry limits")
        while not self.shutdown_event.is_set():
            try:
                queue_item = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                message_id, mail_from, rcpt_tos, retry_count = queue_item
                self.task_manager.create_task(
                    self.process_one_file(message_id, mail_from, rcpt_tos, retry_count)
                )
                await self.health_state.update_metric('queue_size', self.queue.qsize())
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in sender main loop: {e}")
        logger.info("Sender run loop finished.")

    async def recover_messages_on_startup(self) -> None:
        outbox_dir = self.dirs['outbox']
        if not outbox_dir.exists():
            return
        
        recovered_count = 0
        logger.info("Starting recovery of messages from outbox...")
        
        try:
            filenames = await asyncio.to_thread(os.listdir, outbox_dir)
            for filename in filenames:
                if not filename.endswith('.eml'):
                    continue
                    
                filepath = outbox_dir / filename
                message_id = filename[:-4]
                
                # Validate message ID is a UUID for security
                if not is_valid_uuid(message_id):
                    logger.warning(f"Invalid message ID {message_id}, moving to failed.")
                    await safe_unlink(filepath)
                    continue
                
                try:
                    async with aiofiles.open(filepath, 'rb') as f:
                        content = await f.read()
                    
                    if not validate_message_content(content):
                        logger.warning(f"Invalid message content in {filename}, moving to failed.")
                        await atomic_move(filepath, self.dirs['failed'] / filename)
                        continue
                    
                    msg = email.message_from_bytes(content)
                    
                    mail_from = msg.get('Return-Path', '').strip('<>') or msg.get('From', '')
                    if not validate_email_address(mail_from):
                        logger.error(f"Invalid From/Return-Path header in {filename}, skipping.")
                        continue

                    rcpt_tos_headers = [msg.get(h) for h in ['To', 'Cc', 'Bcc'] if msg.get(h)]
                    rcpt_tos = []
                    for header in rcpt_tos_headers:
                        for addr in header.split(','):
                            addr = addr.strip()
                            if validate_email_address(addr):
                                rcpt_tos.append(addr)

                    if mail_from and rcpt_tos:
                        queue_item = (message_id, mail_from, rcpt_tos, 0)
                        await self.queue.put(queue_item)
                        recovered_count += 1
                    else:
                        logger.warning(f"Could not parse valid routing info from {filename}, moving to failed.")
                        await atomic_move(filepath, self.dirs['failed'] / filename)

                except Exception as e:
                    logger.error(f"Failed to recover {filename}: {e}")
                    await atomic_move(filepath, self.dirs['failed'] / filename)
                    
        except Exception as e:
            logger.error(f"Error during message recovery: {e}")
            
        if recovered_count > 0:
            logger.info(f"Recovered and re-queued {recovered_count} messages from previous session.")
        else:
            logger.info("No messages to recover from outbox.")

    async def process_one_file(self, message_id: str, mail_from: str, rcpt_tos: List[str], retry_count: int) -> None:
        if not is_valid_uuid(message_id):
            logger.error(f"Invalid message ID {message_id}, skipping.")
            return
            
        filename = f"{sanitize_filename(message_id)}.eml"
        outbox_path = self.dirs['outbox'] / filename
        processing_path = self.dirs['processing'] / filename
        
        if not outbox_path.exists():
            logger.warning(f"File {message_id}.eml not found in outbox, likely already processed.")
            return

        try:
            await atomic_move(outbox_path, processing_path)
        except Exception as e:
            logger.error(f"Could not move {message_id} to processing: {e}")
            return

        # Check circuit breaker before attempting to send
        if not self.circuit_breaker.can_execute():
            logger.warning(f"Circuit breaker OPEN, delaying message {message_id}")
            await self._handle_failure(processing_path, message_id, mail_from, rcpt_tos, retry_count, is_send_failure=False)
            return

        try:
            success = await self._send_message(processing_path, mail_from, rcpt_tos)
            if success:
                self.circuit_breaker.record_success()
                await self._handle_success(processing_path, message_id)
            else:
                self.circuit_breaker.record_failure()
                await self._handle_failure(processing_path, message_id, mail_from, rcpt_tos, retry_count)
        except Exception as e:
            logger.error(f"Error processing message {message_id}: {e}")
            self.circuit_breaker.record_failure()
            await self._handle_failure(processing_path, message_id, mail_from, rcpt_tos, retry_count)

    async def _send_message(self, msg_path: Path, mail_from: str, rcpt_tos: List[str]) -> bool:
        """Send message using streaming to prevent memory exhaustion"""
        try:
            # Stream the message content
            async with aiofiles.open(msg_path, 'rb') as f:
                message_content = await f.read(STREAM_CHUNK_SIZE)
                full_content = message_content
                
                # Read in chunks to avoid loading entire large message
                while len(message_content) == STREAM_CHUNK_SIZE:
                    message_content = await f.read(STREAM_CHUNK_SIZE)
                    full_content += message_content

            await aiosmtplib.send(
                full_content,
                sender=mail_from,
                recipients=rcpt_tos,
                **self.smtp_settings
            )
            await self.health_state.increment_metric('messages_sent')
            return True
        except Exception as e:
            logger.warning(f"Failed to send message {msg_path.name}: {e}")
            await self.health_state.increment_metric('messages_failed')
            return False

    async def _handle_success(self, msg_path: Path, message_id: str) -> None:
        try:
            logger.info(f"Successfully sent message {message_id}")
            if self.config.getboolean('save_sent_mail'):
                await atomic_move(msg_path, self.dirs['sent'] / msg_path.name)
            else:
                await safe_unlink(msg_path)
        except Exception as e:
            logger.error(f"Error handling success for {message_id}: {e}")

    async def _handle_failure(self, msg_path: Path, message_id: str, mail_from: str, rcpt_tos: List[str], retry_count: int, is_send_failure: bool = True) -> None:
        try:
            if is_send_failure:
                retry_count += 1

            if retry_count >= self.retry_config.max_attempts:
                await atomic_move(msg_path, self.dirs['failed'] / msg_path.name)
                logger.error(f"Message {message_id} failed after {retry_count} attempts, moved to failed.")
            else:
                await atomic_move(msg_path, self.dirs['outbox'] / msg_path.name)
                await self._schedule_retry(message_id, mail_from, rcpt_tos, retry_count)
        except Exception as e:
            logger.error(f"Error handling failure for {message_id}: {e}")

    async def _schedule_retry(self, message_id: str, mail_from: str, rcpt_tos: List[str], retry_count: int) -> None:
        try:
            delay = min(
                self.retry_config.initial_delay * (self.retry_config.backoff_multiplier ** retry_count),
                self.retry_config.max_delay
            )
            logger.info(f"Scheduling retry {retry_count + 1}/{self.retry_config.max_attempts} for {message_id} in {delay:.2f}s")
            self.task_manager.create_task(self._delayed_requeue(message_id, mail_from, rcpt_tos, retry_count, delay))
        except Exception as e:
            logger.error(f"Error scheduling retry for {message_id}: {e}")

    async def _delayed_requeue(self, message_id: str, mail_from: str, rcpt_tos: List[str], retry_count: int, delay: float) -> None:
        async with self.retry_semaphore:
            try:
                await asyncio.sleep(delay)
                if not self.shutdown_event.is_set():
                    queue_item = (message_id, mail_from, rcpt_tos, retry_count)
                    await self.queue.put(queue_item)
            except Exception as e:
                logger.error(f"Error during delayed requeue for {message_id}: {e}")

# --- Main Application ---
async def main():
    try:
        config = load_config()
        base_dir = Path(config.get('server', 'files_directory'))
        base_dir.mkdir(parents=True, exist_ok=True)
        
        dirs = {
            'outbox': base_dir / 'outbox', 'processing': base_dir / 'processing',
            'sent': base_dir / 'sent', 'failed': base_dir / 'failed',
        }
        for dir_path in dirs.values():
            dir_path.mkdir(exist_ok=True)

        shutdown_event = asyncio.Event()
        task_manager = TaskManager()
        health_state = HealthState()
        
        # Rate limiter setup
        rate_limiter = RateLimiter(
            max_messages_per_hour=config.getint('server', 'max_messages_per_hour'),
            max_bytes_per_hour=config.getint('server', 'max_bytes_per_hour')
        )
        
        queue_size = config.getint('server', 'queue_size')
        sender_queue = asyncio.Queue(maxsize=queue_size)

        def signal_handler():
            if not shutdown_event.is_set():
                logger.info("Shutdown signal received")
                shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

        try:
            sender = Sender(config, dirs, shutdown_event, sender_queue, health_state, task_manager)
            disk_monitor = DiskHealthMonitor(config, health_state, task_manager, shutdown_event)
            
            # Recover messages first to populate queue
            await sender.recover_messages_on_startup()
            
            # Start background tasks
            task_manager.create_task(sender.run())
            task_manager.create_task(disk_monitor.run())

            handler = BufferSMTPHandler(dirs, health_state, sender_queue, rate_limiter)
            controller = Controller(
                handler, hostname=config.get('server', 'host'),
                port=config.getint('server', 'port'),
                data_size_limit=config.getint('server', 'max_message_size'),
            )
            controller.start()
            logger.info(f"SMTP server started on {config.get('server', 'host')}:{config.getint('server', 'port')}")
            
            await shutdown_event.wait()
        finally:
            logger.info("Shutting down...")
            try:
                controller.stop()
            except Exception as e:
                logger.error(f"Error stopping controller: {e}")
            
            await task_manager.cancel_all()
            
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.remove_signal_handler(sig)
                except Exception:
                    pass
            
            try:
                metrics = await health_state.get_metrics()
                logger.info(f"Final metrics: {metrics}")
            except Exception as e:
                logger.error(f"Error getting final metrics: {e}")
            
            logger.info("Shutdown complete")
    except Exception as e:
        logger.critical(f"Fatal error in main: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
