import sys, getopt, socket, time, SoftLayer, json, string, configparser, os, argparse, csv, math, logging, requests
from datetime import datetime, timedelta, tzinfo
import pytz

import sendgrid
from twilio.rest import TwilioRestClient

# put your own credentials here
ACCOUNT_SID = "AC06837c4494699c87dbf6f7e4d80477a3"
AUTH_TOKEN = "bb65f9610c5c7c810dbf311e81e1c1d2"
smsclient = TwilioRestClient(ACCOUNT_SID, AUTH_TOKEN)


def convert_timedelta(duration):
    days, seconds = duration.days, duration.seconds
    hours = days * 24 + seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    totalminutes = round((days * 1440) + (hours * 60) + minutes + (seconds / 60), 1)
    return totalminutes


def convert_timestamp(sldate):
    formatedDate = sldate
    formatedDate = formatedDate[0:19]
    formatedDate = datetime.strptime(formatedDate, "%Y-%m-%dT%H:%M:%S")
    return formatedDate


def getDescription(categoryCode, detail):
    for item in detail:
        if item['categoryCode'] == categoryCode:
            return item['description']
    return "Not Found"


def initializeSoftLayerAPI(user, key, configfile):
    if user == None and key == None:
        if configfile != None:
            filename = args.config
        else:
            filename = "config.ini"
        config = configparser.ConfigParser()
        config.read(filename)
        client = SoftLayer.Client(username=config['api']['username'], api_key=config['api']['apikey'],
                                  endpoint_url=SoftLayer.API_PRIVATE_ENDPOINT)
    else:
        # client = SoftLayer.Client(username=config['api']['username'], api_key=config['api']['apikey'],endpoint_url=SoftLayer.API_PRIVATE_ENDPOINT)
        client = SoftLayer.Client(username=user, api_key=key)
    return client


# def sendsms(email,subject, body):
#    sg = sendgrid.SendGridClient('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')
#    message = sendgrid.Mail()
#    message.add_to(email)
#    message.set_subject(subject)
#    message.set_html(body)
#    message.set_from('Jon Hall <jonhall@us.ibm.com>')
#    status, msg = sg.send(message)


#
# Get APIKEY from config.ini & initialize SoftLayer API
#


## READ CommandLine Arguments and load configuration file
parser = argparse.ArgumentParser(description="Check Audit Log for VSI.")
parser.add_argument("-u", "--username", help="SoftLayer API Username")
parser.add_argument("-k", "--apikey", help="SoftLayer APIKEY")
parser.add_argument("-c", "--config", help="config.ini file to load")
args = parser.parse_args()

client = initializeSoftLayerAPI(args.username, args.apikey, args.config)

today = datetime.now()
startdate = datetime.strftime(today, "%m/%d/%Y") + " 0:0:0"
enddate = datetime.strftime(today, "%m/%d/%Y") + " 23:59:59"

# print ('%s Checking Provisioning Events.' % (datetime.strftime(datetime.now(),"%m/%d/%Y %H:%M:%S")))
logging.basicConfig(filename='events.log', format='%(asctime)s %(message)s', level=logging.INFO)

run = ""
previouscritical = 0
while run is "":
    virtualGuests = client['Account'].getHourlyVirtualGuests(
        mask='id, provisionDate, hostname, activeTicketCount, lastTransaction, activeTransaction, activeTransactions,datacenter, serverRoom',
        filter={
            'hourlyVirtualGuests': {
                'provisionDate': {'operation': 'is null'}
            }
        })
    logging.info('Found %s VirtualGuests being provisioned.' % (len(virtualGuests)))
    # print (json.dumps(virtualGuests,indent=4))
    # Open a file in write mode
    output = open("events.txt", "a")
    output.write("\n\n")
    output.write('Provisioning Status Detail at: %s\n' % (datetime.strftime(datetime.now(), "%m/%d/%Y %H:%M:%S")))
    output.write('{:<10} {:<15} {:<12} {:<8} {:<15} {:<8} {:<8} {:<20} {:<15} {:<10}\n'.format("guestId", "hostName",
                                                                                               "datacenter", "tickets",
                                                                                               "createDate", "PowerOn",
                                                                                               "delta",
                                                                                               "transactionStatus",
                                                                                               "statusDuration",
                                                                                               "Status"))

    countVirtualGuestslt30 = 0
    countVirtualGuestsgt30 = 0
    countVirtualGuestsgt60 = 0
    countVirtualGuestsgt120 = 0
    ontrack = 0
    critical = 0
    watching = 0
    stalled = 0
    ticket = []

    for virtualGuest in virtualGuests:
        Id = virtualGuest['id']
        guestId = virtualGuest['activeTransaction']['guestId']
        createDate = virtualGuest['activeTransaction']['createDate']
        createDateStamp = convert_timestamp(createDate)
        currentDateStamp = datetime.now()
        delta = convert_timedelta(currentDateStamp - createDateStamp)
        hostName = virtualGuest['hostname']
        datacenter = virtualGuest['datacenter']['name']
        tickets = virtualGuest['activeTicketCount']
        if guestId not in ticket:
            ticket.append({guestId: {'count': 0, 'previouscount': 0}})
        else:
            ticket[guestId]['count'] = tickets
        transactionStatus = virtualGuest['activeTransaction']['transactionStatus']['name']
        statusDuration = virtualGuest['activeTransaction']['elapsedSeconds']

        if tickets > 0:
            message = ("%s Tickets open on guestID %s." % (tickets, guestId))
            smsclient.messages.create(
                to="14025988805",
                from_="+14025908566",
                body=message,
            )
            logging.info("Sending SMS message due to ticket status of GuestId %s." % (guestId))

        events = ""
        logging.info('Searching eventlog for POWERON detail for guestId %s.' % (guestId))
        while events is "":
            try:
                events = client['Event_Log'].getAllObjects(filter={'objectId': {'operation': guestId},
                                                                   'eventName': {'operation': 'Power On'}})
            except SoftLayer.SoftLayerAPIError as e:
                logging.warning("Error: %s, %s" % (e.faultCode, e.faultString))
                time.sleep(5)
        found = 0
        powerOnDateStamp=datetime.now()
        for event in events:
            if event['eventName']=="Power On":

                eventdate = event["eventCreateDate"]
                #eventdate = eventdate[0:29] + eventdate[-2:]
                #Strip TZ off
                eventdate = eventdate[0:26]
                eventdate = datetime.strptime(eventdate, "%Y-%m-%dT%H:%M:%S.%f")

                if eventdate < powerOnDateStamp:
                    powerOnDateStamp = eventdate
                    found = 1

        if found == 1:
            logging.info('POWERON detail for guestId %s FOUND.' % (guestId))
            powerOnDelta = convert_timedelta(powerOnDateStamp - createDateStamp)
        else:
            logging.info('POWERON detail for guestId %s NOT FOUND.' % (guestId))
            powerOnDelta = 0

        status="unknown"
        logging.info('Classifying provisioning status for guestId %s.' % (guestId))
        if powerOnDelta == 0:
            # IF LESS THAN 30 MINUTES NO PROBLEM ON TRACK
            if delta <= 30:
                status = "ONTRACK/NOPWR"
                ontrack = ontrack + 1
            # IF NO POWERON AFTER 30 MINUTES MARK CRITICAL
            if delta > 30:
                status = "CRITICAL/NOPWR"
                critical = critical + 1
            if delta > 120:
                status = "STALLED/NOPWR"
                stalled = stalled + 1
        else:
            # IF LESS THAN 30 MINUTES NO PROBLEM ON TRACK
            if (delta - powerOnDelta) <= 30:
                status = "ONTRACK/PWR"
                ontrack = ontrack + 1
            # IF TOTAL TIME MINUS POWERON BETWEEN 30-60 MINUTES WERE GOOD BUT WATCH.
            if (delta - powerOnDelta) > 30 and (delta - powerOnDelta) < 60:
                status = "ATRISK/PWR"
                watching = watching + 1
            # IF TOTAL TIME MINUS POWERON LONGER THAN AN HOUR BUT LESS THAN 2 MARK CRITICAL.
            if (delta - powerOnDelta) > 60 and (delta - powerOnDelta) < 120:
                status = "CRITICAL/PWR"
                critical = critical + 1
            # ANything over 2 hours cosnider stalled.
            if delta > 120:
                status = "STALLED/PWR"
                stalled = stalled + 1

        output.write(
            '{:<10} {:<15} {:<12} {:<8} {:<15} {:<8} {:<8} {:<20} {:<15} {:<10}\n'.format(guestId, hostName, datacenter,
                                                                                          tickets, createDate,
                                                                                          powerOnDelta, delta,
                                                                                          transactionStatus,
                                                                                          statusDuration, status))


        if delta < 30:
            countVirtualGuestslt30 = countVirtualGuestslt30 + 1
        if delta >= 30 and delta < 60:
            countVirtualGuestsgt30 = countVirtualGuestsgt30 + 1
        if delta >= 60 and delta < 120:
            countVirtualGuestsgt60 = countVirtualGuestsgt60 + 1
        if delta >= 120:
            countVirtualGuestsgt120 = countVirtualGuestsgt120 + 1

    output.write("\n")
    output.write("Total:%s | <30:%s | >30:%s | >60:%s | >120:%s\n" % (
        len(virtualGuests), countVirtualGuestslt30, countVirtualGuestsgt30, countVirtualGuestsgt60,
        countVirtualGuestsgt120))
    output.write("OnTrack: %s | Watching: %s | Critical:%s | Stalled:%s\n" % (ontrack, watching, critical, stalled))

    logging.info("T:%s | <30:%s | >30:%s | >60:%s | >120:%s | OnTrack: %s | Watching: %s | Critical:%s | Stalled:%s" % (
        len(virtualGuests), countVirtualGuestslt30, countVirtualGuestsgt30, countVirtualGuestsgt60, countVirtualGuestsgt120,
        ontrack, watching, critical, stalled))

    if critical > previouscritical:
        # Send SMS message
        message = (
                "T:%s | <30:%s | >30:%s | >60:%s | >120:%s | OnTrack: %s | Watching: %s | Critical:%s | Stalled:%s" % (
                len(virtualGuests), countVirtualGuestslt30, countVirtualGuestsgt30, countVirtualGuestsgt60,
                countVirtualGuestsgt120, ontrack, watching, critical, stalled))
        smsclient.messages.create(
                to="14025988805",
                from_="+14025908566",
                body=message,
        )
        # Trigger Maker Receipe with details
        url = 'https://maker.ifttt.com/trigger/aficritical/with/key/jehAniL4SfD0glj5AR4IZ5EJKkDJ5uwYfsyEkL7r4_L'
        data = {'value1': len(virtualGuests),
                'value2': critical,
                'value3': stalled}
        req = requests.post(url, json=data)
        previouscritical = critical
        logging.info("Sending SMS message due to increase in critical change.")
    output.close()
    time.sleep(300)