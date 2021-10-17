# Arnie - SMTP buffer server in < 100 lines of async Python


Created 17 Oct 2021 by Andrew Stuart andrew.stuart@supercoders.com.au

-------------------------------
**Purpose**:

Web applications often need to send emails.

Ideally the web server code doesn't actually talk directly to an SMTP server.  Instead it should somehow queue/buffer the email for sending.  This ensures the web page can return to the user as quickly as possible instead of waiting for the SMTP send to actually complete.

I wrote this because I got frustrated using complex queueing systems simply to buffer outbound SMTP emails.

-------------------------------
**Project status**:

Created 17 Oct 2021 by Andrew Stuart andrew.stuart@supercoders.com.au

License: MIT

####IMPORTANT!!! This is  NEW project, it is not battle tested! Use at your own risk.

##Instructions to install Arnie on Ubuntu Linux:

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
Arnie is a single Python file. Save the arniesmtpbufferserver.py from the github repo.

You are now ready to run Arnie.

##Running Arnie:

**Requires minimum Python 3.8**

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
```
OUTBOUND_EMAIL_USE_TLS - whether to use TLS for your destination SMTP server  
OUTBOUND_EMAIL_HOST - host address for your destination SMTP server 
OUTBOUND_EMAIL_USERNAME - username for your destination SMTP server
OUTBOUND_EMAIL_PASSWORD - password for your destination SMTP server
OUTBOUND_EMAIL_HOST_PORT - port number  for your destination SMTP server
ADMIN_ADDRESS - the Arnie server sends an email every hour to this address with a count of failed sends. (do not set this if you do not want to receive report emails)
SAVE_SENT_MAIL - if true, then sent emails are saved in the FILES_DIRECTORY/failed
ARNIE_LISTEN_PORT - default is 8025 - the port number that the Arnie server listens on for inbound SMTP messages
FILES_DIRECTORY - where Arnie should store the buffered email files
```

Start the Arnie server:

```
source venv3/bin/activate
python arniesmtpbufferserver.py
```

Send a test email via Arnie with curl (modify this line and replace the email addresses):

```
printf "To: foo@example.org\r\nFrom: foo@example.org\r\nSubject: A test from Arnie\r\n\r\nI'll be back." | curl smtp://127.0.0.1:8025 --mail-from foo@example.org --mail-rcpt foo@example.org -T -
```

##Security important!

This should not need saying but I'll say it anyway: Arnie is an open mail relay.
 
The ARNIE_LISTEN_PORT SHOULD NOT BE EXPOSED TO THE INTERNET - YOU HAVE BEEN WARNED!

##To run as a service on Linux

Go to the directory where systemd service files are stored:

```
cd /etc/systemd/system
```

Download the systemd service file from github:

```
sudo curl -O https://raw.githubusercontent.com/bootrino/arniesmtpbufferserver/master/etc/systemd/system/arniesmtpbufferserver.service
```








-------------------------------

