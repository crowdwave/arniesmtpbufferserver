# arniesmtpbufferserver v1
# copyright 2021 Andrew Stuart andrew.stuart@supercoders.com.au
# MIT licensed

# this is an SMTP email buffer server - useful for web servers

import asyncio, logging, time, os, subprocess, aiosmtplib, email, sys, signal, textwrap, dotenv
from aiosmtpd.controller import Controller

dotenv.load_dotenv()  # take environment variables from .env.
required_envvars = ['OUTBOUND_EMAIL_USE_TLS', 'OUTBOUND_EMAIL_HOST', 'OUTBOUND_EMAIL_USERNAME',
                    'OUTBOUND_EMAIL_PASSWORD', 'OUTBOUND_EMAIL_HOST_PORT', 'FILES_DIRECTORY']
if not all(item in os.environ.keys() for item in required_envvars):
    print(f'These environment variables must be set: \n{",".join(required_envvars)}')
    sys.exit(1)
OUTBOUND_EMAIL_USE_TLS = os.environ.get('OUTBOUND_EMAIL_USE_TLS') in ['1', 'true', 'yes']
OUTBOUND_EMAIL_HOST = os.environ.get('OUTBOUND_EMAIL_HOST')
OUTBOUND_EMAIL_USERNAME = os.environ.get('OUTBOUND_EMAIL_USERNAME')
OUTBOUND_EMAIL_PASSWORD = os.environ.get('OUTBOUND_EMAIL_PASSWORD')
OUTBOUND_EMAIL_HOST_PORT = int(os.environ.get('OUTBOUND_EMAIL_HOST_PORT'))
ADMIN_ADDRESS = os.environ.get('ADMIN_ADDRESS', None)
SAVE_SENT_MAIL = os.environ.get('SAVE_SENT_MAIL') in ['1', 'true', 'yes']
ARNIE_LISTEN_PORT = int(os.environ.get('ARNIE_LISTEN_PORT', 8025))

MAX_SEND_ATTEMPTS = 3
POLL_WAIT = 10  # seconds
FILES_DIRECTORY = os.environ.get('FILES_DIRECTORY', '')  # current directory if not specified in an environment variable
if not FILES_DIRECTORY.endswith('/') and FILES_DIRECTORY != '':
    FILES_DIRECTORY += '/'
PREFIX = f'{FILES_DIRECTORY}arniefiles'


async def reporting(loop):
    # periodically send a reporting email
    if not ADMIN_ADDRESS:
        return
    while True:
        message = email.message_from_string(textwrap.dedent(f"""\
                From: {ADMIN_ADDRESS}
                To: {ADMIN_ADDRESS}
                Subject: arniesmtpbufferserver: failed count: {len(os.listdir(f'{PREFIX}/failed'))} """))
        await aiosmtplib.send(message, hostname='localhost', port=ARNIE_LISTEN_PORT)
        await asyncio.sleep(3600)  # once an hour


async def shutdown(signal, loop):
    # credit to Lynn Root for the shutdown code https://www.roguelynn.com/words/asyncio-graceful-shutdowns/
    logging.info(f"Received exit signal {signal.name}...")
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    [task.cancel() for task in tasks]
    logging.info(f"Cancelling {len(tasks)} outstanding tasks")
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


async def send_mail(loop):
    creation_time_of_last_processed_file = 0
    sent_attempts = {}
    while True:
        # we need to process the oldest file in the outbox directory BUT must always ignore those already processed
        files_in_outbox = [f'{PREFIX}/outbox/{x}' for x in os.listdir(f'{PREFIX}/outbox')
                           if os.path.getctime(f'{PREFIX}/outbox/{x}') > creation_time_of_last_processed_file]
        if not files_in_outbox:
            # no emails to send
            creation_time_of_last_processed_file = 0
            await asyncio.sleep(POLL_WAIT)
            continue
        oldest_file_path = min(files_in_outbox, key=os.path.getctime)
        creation_time_of_last_processed_file = os.path.getctime(oldest_file_path)
        print('creation_time_of_last_processed_file: ', creation_time_of_last_processed_file)
        oldest_file_name = oldest_file_path.split('/')[-1]
        with open(oldest_file_path, 'rb') as f:
            message = email.message_from_binary_file(f)
        try:
            await aiosmtplib.send(message, hostname=OUTBOUND_EMAIL_HOST, port=OUTBOUND_EMAIL_HOST_PORT,
                                  username=OUTBOUND_EMAIL_USERNAME,
                                  password=OUTBOUND_EMAIL_PASSWORD, start_tls=OUTBOUND_EMAIL_USE_TLS)
            if SAVE_SENT_MAIL:
                os.rename(oldest_file_path, f'{PREFIX}/sent/{oldest_file_name}')
            else:
                os.remove(oldest_file_path)
        except Exception as e:
            logging.info(f'ERROR SENDING: {oldest_file_path} {repr(e)}')
            if oldest_file_path in sent_attempts.keys():
                if sent_attempts[oldest_file_path] > MAX_SEND_ATTEMPTS:
                    os.rename(oldest_file_path, f'{PREFIX}/failed/{oldest_file_name}')
                    # stop tracking attempts for this file
                    sent_attempts.pop(oldest_file_path, None)
                    continue
                sent_attempts[oldest_file_path] += 1
            else:
                sent_attempts[oldest_file_path] = 0
            continue
        logging.info(f'sent: sent/{oldest_file_name} from: {message.get("From")}')


class ReceiveHandler:
    async def handle_VRFY(self, server, session, envelope, addr):
        return '252 send some mail'

    async def handle_DATA(self, server, session, envelope):
        filename = f'{time.time_ns()}.eml'
        with open(f'{PREFIX}/inbox/{filename}', 'wb') as f:
            f.write(envelope.original_content)
        os.rename(f'{PREFIX}/inbox/{filename}', f'{PREFIX}/outbox/{filename}')
        logging.info(f'outbox/{filename} from {envelope.mail_from}')
        return '250 Message accepted for delivery'


async def receive_mail(loop):
    controller = Controller(ReceiveHandler(), hostname='', port=ARNIE_LISTEN_PORT)
    controller.start()


if __name__ == '__main__':
    subprocess.run(["mkdir", "-p", f"{PREFIX}/inbox", f"{PREFIX}/outbox", f"{PREFIX}/sent", f"{PREFIX}/failed"])
    logging.basicConfig(level=logging.DEBUG)
    loop = asyncio.get_event_loop()
    signals = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    for s in signals:
        loop.add_signal_handler(s, lambda s=s: asyncio.create_task(shutdown(s, loop)))
    try:
        loop.create_task(receive_mail(loop=loop))
        loop.create_task(send_mail(loop=loop))
        loop.create_task(reporting(loop=loop))
        loop.run_forever()
    finally:
        loop.close()
