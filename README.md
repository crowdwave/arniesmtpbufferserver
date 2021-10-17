# Arnie - SMTP buffer server in ~ 100 lines of async Python

Created 17 Oct 2021 by Andrew Stuart andrew.stuart@supercoders.com.au

License: MIT

**Requires minimum Python 3.8**

## Purpose of Arnie.

Web applications often need to send emails.

Ideally the web server code doesn't actually talk directly to an SMTP server.  Instead it should somehow queue/buffer the email for sending.  This ensures the web page can return to the user as quickly as possible instead of waiting for the SMTP send to actually complete.

This server is intended for small scale usage - for example a typical web server for a simple SAAS application.  It may work for large scale email traffic but it's unknown how it would handle such load.

Arnie seqentially sends emails - it does not attempt to send email to the SMTP server in parallel.  It probably could do fairly easily by spawning email send tasks, but SMTP parallelisation was not the goal in writing Arnie.

### Project status:

This is  NEW project, it is not battle tested! Use at your own risk. This server is written to meet my own personal needs - as such I do not need to, want to, nor can I afford to write tests.  

Arnie is not intended to be a professional production quality email server ...... it's for technically experienced people who know what they are doing and are happy to read the Python code and accept the risks.

I wrote Arnie because I got frustrated using complex queueing systems simply to buffer outbound SMTP emails. I'd rather spend time writing this than spend the same time debugging Celery configuration.

## Credits:

Credit to Lynn Root for Arnie's shutdown code https://www.roguelynn.com/words/asyncio-graceful-shutdowns/

## Installing Arnie:

Make a directory:
```
sudo mkdir /opt/arniesmtpbufferserver
```

Set permissions on the directory. For example if you plan to run the server as username ubuntu:
```
sudo chown -R :ubuntu /opt/arniesmtpbufferserver/
sudo chmod -R g+rwx /opt/arniesmtpbufferserver/
```

Check your version of Python is at least 3.8:

```
python3 -V
> Python 3.8.10
```

Switch to the directory:

```
cd /opt/arniesmtpbufferserver/
```
Download the Arnie Python program file from github:

```
curl -O https://raw.githubusercontent.com/bootrino/arniesmtpbufferserver/master/arniesmtpbufferserver.py
curl -O https://raw.githubusercontent.com/bootrino/arniesmtpbufferserver/master/.env
```
Create a Python venv:

```
python3 -m venv venv3
```

Activate the venv:

```
source venv3/bin/activate
```

Install the required libraries into the venv:

```
pip install wheel                             
pip install aiosmtplib                             
pip install aiosmtpd 
pip install python-dotenv
```

Run Arnie:

```
python3 arniesmtpbufferserver.py
```

Arnie should now start and be ready to send email.

To send an email via Arnie, use any SMTP sending program, with the port address equal to the ARNIE_LISTEN_PORT default is 8025. No username or password is required when sending. 

## Security important!

Arnie is an open mail relay - it has no security - it is intended to be accessed only as a local service on a server.
 
The ARNIE_LISTEN_PORT SHOULD NOT BE EXPOSED TO THE INTERNET!

## Running Arnie:

Prior to running the server, you must set certain environment variables in the .env file.

In an earlier step we downloaded the example .env file from github.

Edit that file now and configure it as you choose.

Here is an example for using Amazon Simple Email Service:
```
OUTBOUND_EMAIL_USE_TLS=true
OUTBOUND_EMAIL_HOST=email-smtp.eu-west-1.amazonaws.com 
OUTBOUND_EMAIL_USERNAME=AKIAUU821WSDPIBFFYYV
OUTBOUND_EMAIL_PASSWORD=BL+Ctcgdg93prPZjnUkJFIpP1cEew3mqhDkqCHvbKIzR
OUTBOUND_EMAIL_HOST_PORT=587
ADMIN_ADDRESS=someone.who.cares.if.email.is.working@example.org
SAVE_SENT_MAIL=true
ARNIE_LISTEN_PORT=8025
FILES_DIRECTORY=~
```

Explanation of environment variables:

**OUTBOUND_EMAIL_USE_TLS** - whether to use TLS for your destination SMTP server  
**OUTBOUND_EMAIL_HOST** - host address for your destination SMTP server 
**OUTBOUND_EMAIL_USERNAME** - username for your destination SMTP server
**OUTBOUND_EMAIL_PASSWORD** - password for your destination SMTP server
**OUTBOUND_EMAIL_HOST_PORT** - port number  for your destination SMTP server
**ADMIN_ADDRESS** - the Arnie server sends an email every hour to this address with a count of failed sends. (do not set this if you do not want to receive report emails)
**SAVE_SENT_MAIL** - if true, then sent emails are saved in the FILES_DIRECTORY/failed
**ARNIE_LISTEN_PORT** - default is 8025 - the port number that the Arnie server listens on for inbound SMTP messages
**FILES_DIRECTORY** - where Arnie should store the buffered email files

Start the Arnie server:

```
source venv3/bin/activate
python arniesmtpbufferserver.py
```

Send a test email via Arnie with curl (modify this line and replace the email addresses):

```
printf "To: foo@example.org\r\nFrom: foo@example.org\r\nSubject: A test from Arnie\r\n\r\nI'll be back." | curl smtp://127.0.0.1:8025 --mail-from foo@example.org --mail-rcpt foo@example.org -T -
```

## To run as a systemd service on Linux

Go to the directory where systemd service files are stored:

```
cd /etc/systemd/system
```

Download the systemd service file from github:

```
sudo curl -O https://raw.githubusercontent.com/bootrino/arniesmtpbufferserver/master/etc/systemd/system/arniesmtpbufferserver.service
```

Start the systemd service:

```
sudo systemctl start arniesmtpbufferserver.service
```

Examine the systemd log to ensure the service is running OK:

```
sudo journalctl -fu arniesmtpbufferserver.service
```

Enable the service to start when the system boots:

```
sudo systemctl enable arniesmtpbufferserver.service
```

You should now have Arnie running as a systemd service.

<hr style="border:1px solid gray"/> 

