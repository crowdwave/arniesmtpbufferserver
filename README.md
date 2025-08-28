# Arnie - SMTP buffer server

# DO NOT USE THIS IN PRODUCTION IT IS A DEMONSTRATION ONLY WITH LIKELY LOGIC AND OTHER FLAWS

Created 17 Oct 2021 by Andrew Stuart andrew.stuart@supercoders.com.au

License: MIT

**Requires minimum Python 3.8**

## What is Arnie and why should you use it?

Arnie is a server that has the single purpose of buffering outbound SMTP emails.

A typical web SAAS needs to send emails such as signup/signin/forgot password etc. 

The web page code itself should not directly write this to an SMTP server. Instead they should be decoupled. There's a few reasons for this. One is, if there is an error in sending the email, then the whole thing simply falls over if that send was executed by the web page code - there's no chance to resend because the web request has completed. Also, execution of an SMTP request by a web page slows the response time down of that page, whilst the code goes through the process of connecting to the server and sending the email. So when you send SMTP email from your web application, the most performant and safest way to do it is to buffer them for sending. The buffering server will then queue them and send them and handle things like retries if the target SMTP server is down or throttled. 

There's a few ways to solve this problem - you can set up a local email server and configure it for relaying. Or in the Python world people often use Celery.  Complexity is the down side of using either Celery or an email server configured for relaying - both of these solutions have many more features than needed and can be complex to configure/run/troubleshoot.

Arnie is intended for small scale usage - for example a typical web server for a simple SAAS application.  Large scale email traffic would require parallel sends to the SMTP server.

Arnie seqentially sends emails - it does not attempt to send email to the SMTP server in parallel.  It probably could do fairly easily by spawning email send tasks, but SMTP parallelisation was not the goal in writing Arnie.

### Project status:

**This is  NEW project, it is not battle tested! Use at your own risk.  There will be bugs.** This server is written to meet my own personal needs - as such I do not need to, want to, nor can I afford to write tests.  

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
**ADMIN_ADDRESS** - the Arnie server sends an email every hour to this address with a count of failed sends. (omit this environment variable if you do not want to receive report emails)  
**SAVE_SENT_MAIL** - if true, then sent emails are saved in the FILES_DIRECTORY/sent  
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

Examine the systemd service file and check all the directories are correct for your setup.  Edit if needed.

```
cat /etc/systemd/system/arniesmtpbufferserver.service
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

