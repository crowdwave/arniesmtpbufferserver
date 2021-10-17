# arniemailbufferserver v1
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

MAX_SEND_ATTEMPTS = 50
FILES_DIRECTORY = os.environ.get('FILES_DIRECTORY', '')  # current directory if not specified in an environment variable
if not FILES_DIRECTORY.endswith('/') and FILES_DIRECTORY != '':
    FILES_DIRECTORY += '/'
PREFIX = f'{FILES_DIRECTORY}arniefiles'
RETRY_DELAY_SECONDS = 60 * 1 # 1 minute
POLL_WAIT_SECONDS = min(10, RETRY_DELAY_SECONDS)  # seconds ( cannot be larger than RETRY_DELAY_SECONDS)

async def reporting(loop):
    # periodically send a reporting email
    if ADMIN_ADDRESS:
        while True:
            await asyncio.sleep(3600)  # once an hour
            if len(os.listdir(f'{PREFIX}/failed')) > 0:
                message = email.message_from_string(textwrap.dedent(f"""\
                        From: {ADMIN_ADDRESS}
                        To: {ADMIN_ADDRESS}
                        Subject: arniemailbufferserver: failed count: {len(os.listdir(f'{PREFIX}/failed'))} """))
                await aiosmtplib.send(message, hostname='localhost', port=ARNIE_LISTEN_PORT)


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
    # the send_mail process continously sends the oldest file in the outbox.
    # each iteration records the creation_time_of_last_processed_file
    # files older than the creation_time_of_last_processed_file are discarded from each loop
    # therefore each iteration keeps advancing forward by time to the next oldest file.
    # retries:
    # retries are pushed into the future by some period of time RETRY_DELAY_SECONDS
    # we do this by changing the modified time of file into the future
    # files that have a modified time in the future are discarded from each loop
    # the retry mechanism is hacky but simple
    while True:
        # get files in outbox
        files_in_outbox = [f'{PREFIX}/outbox/{x}' for x in os.listdir(f'{PREFIX}/outbox')]
        # discard files that are older than the creation_time_of_last_processed_file
        files_in_outbox = [x for x in files_in_outbox if os.path.getctime(x) > creation_time_of_last_processed_file]
        # discard files that have a modified time in the future
        files_in_outbox = [x for x in files_in_outbox if os.path.getmtime(x) > time.time()]
        if not files_in_outbox:
            # no emails to send
            creation_time_of_last_processed_file = 0
            await asyncio.sleep(POLL_WAIT_SECONDS)
            continue
        oldest_file_in_outbox = min(files_in_outbox, key=os.path.getctime)
        creation_time_of_last_processed_file = os.path.getctime(oldest_file_in_outbox)
        oldest_file_name = oldest_file_in_outbox.split('/')[-1]
        with open(oldest_file_in_outbox, 'rb') as f:
            message = email.message_from_binary_file(f)
        try:
            await aiosmtplib.send(message, hostname=OUTBOUND_EMAIL_HOST, port=OUTBOUND_EMAIL_HOST_PORT,
                                  username=OUTBOUND_EMAIL_USERNAME,
                                  password=OUTBOUND_EMAIL_PASSWORD, start_tls=OUTBOUND_EMAIL_USE_TLS)
            if SAVE_SENT_MAIL:
                os.rename(oldest_file_in_outbox, f'{PREFIX}/sent/{oldest_file_name}')
            else:
                os.remove(oldest_file_in_outbox)
        except Exception as e:
            logging.info(f'ERROR SENDING: {oldest_file_in_outbox} {repr(e)}')
            # set the file modified time into the future - retry will not happen before this time
            os.utime(oldest_file_in_outbox, (creation_time_of_last_processed_file, time.time() + (RETRY_DELAY_SECONDS * 1000)))
            if oldest_file_in_outbox in sent_attempts.keys():
                if sent_attempts[oldest_file_in_outbox] > MAX_SEND_ATTEMPTS:
                    os.rename(oldest_file_in_outbox, f'{PREFIX}/failed/{oldest_file_name}')
                    # stop tracking attempts for this file
                    sent_attempts.pop(oldest_file_in_outbox, None)
                    continue
                sent_attempts[oldest_file_in_outbox] += 1
            else:
                sent_attempts[oldest_file_in_outbox] = 0
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
