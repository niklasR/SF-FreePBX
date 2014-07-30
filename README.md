SF-FreePBX
==========

Log FreePBX/Asterisk calls in SalesForce

## Requirements

SF-FreePBX runs in environments with:
 
 * FreePBX (tested with 2.10.1.5)
 * SalesForce with API access enabled (Enterprise/Performance/Unlimited or Professional with Add-On)

The machine running SF-FreePBX requires
 * Python 2.7
 * telnet access to the PBX server

Names for the extensions need to be saved in the format `$FirstName $LastName` in FreePBX, and accordingly in SalesForce.

## Installation
### FreePBX

Two Asterisk Management Interface (*AMI*) users need to be configured on the PBX server. By default, the configuration file for this can be found at `/etc/asterisk/manager.conf`.
One user needsw to have write-permissions for 'command', and the other one read-permissions for 'cdr'. Make sure they are accessible by the machine you are planning to run SF-FreePBX on.

SF-FreePBX is expecting the database keys for the cidnames in FreePBX to be formatted as `/AMPUSER/0000/cidname` where 0000 is the extension of the user.
The last name of the user in the cidname needs to be the same as the user's last name in SalesForce.

### Salesforce

You need a user with the permissions to create tasks (i.e. log calls/activity) on all accounts, and assign them to anyone. Note down the user's username, password and security token. If you don't have a record of the security token, you can reset it at
 1. Setup
 2. Under *Personal Setup*: My Personal Information
 3. Reset My Security token.

### SF-FreePBX

SF-FreePBX requires Python and [Simple-Salesforce](https://github.com/neworganizing/simple-salesforce/).
Simple Salesforce can be installed with `pip install simple-salesforce`.

## Configuration

Fill out the config files `ast_login.py` and `sf_login.py` with the relevant details.
Your salesforce instance can be taken from the url when you are logged-in to . If it begins with `https://na1.salesforce.com`, for example, your instance would be `na1.salesforce.com`.

## Run

Just run `python pbxSF.py` and it should connect to Asterisk and SalesForce. You should see `FULLY BOOTED, starting loop`. If not, make sure everything is configured correctly.

##Security

Bear in mind that the connection between SF-FreePBX and Asterisk is plaintext, so binding the AMI users to a specific machine, tunneling the traffic or runninf SF-FreePBX on the Asterisk-Sever is recommended.
