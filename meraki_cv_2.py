#!/usr/bin/env python
"""This script:
    launches an MQTT Client
    Subscribes to MV camera flows
    Requests camera snapshot URL from the Meraki API
    Send the snapshot URL to AWS Rekognition
    Receives the response from AWS Recognition
    Sends a formatted response to NodeRed via mqtt """


import configparser
import sys
import json
import requests
import boto3
import paho.mqtt.client as mqtt
import time


def get_meraki_snapshots(session, api_key, net_id, time=None):
    #print('getmerakisnapshots')
    """Get devices of network"""
    headers = {
        'X-Cisco-Meraki-API-Key': api_key,
        # 'Content-Type': 'application/json'
        # issue where this is only needed if timestamp specified
    }
    response = session.get(f'https://api.meraki.com/api/v0/networks/{net_id}/devices',
                           headers=headers)
    devices = response.json()
    #filter for MV cameras:
    cameras = [device for device in devices if device['model'][:2] == 'MV']
    # Assemble return data
    for camera in cameras:
        #filter for serial number provided
        if (camera["serial"] == MV_SERIAL):
            # Get snapshot link
            if time:
                headers['Content-Type'] = 'application/json'
                response = session.post(
                    f'https://api.meraki.com/api/v0/networks/{net_id}/cameras/{camera["serial"]}/snapshot',
                    headers=headers,
                    data=json.dumps({'timestamp': time}))
            else:
                response = session.post(
                    f'https://api.meraki.com/api/v0/networks/{net_id}/cameras/{camera["serial"]}/snapshot',
                    headers=headers)

            # Possibly no snapshot if camera offline, photo not retrievable, etc.
            if response.ok:
                snapshot_url = response.json()['url']

    return snapshot_url

def gather_credentials():
    #print('gatherCreds')
    """Gather Meraki credentials"""
    conf_par = configparser.ConfigParser()
    try:
        conf_par.read('credentials.ini')
        cam_key = conf_par.get('meraki', 'key')
        net_id = conf_par.get('meraki', 'network')
        mv_serial = conf_par.get('sense', 'serial')
        server_ip = conf_par.get('server', 'ip')
    except:
        print('Missing credentials or input file!')
        sys.exit(2)
    return cam_key, net_id, mv_serial, server_ip

def send_snap_to_aws(image):
    """send the snapshot URL to AWS Rekognition"""
    boto_session = boto3.Session(profile_name='default')
    rek = boto_session.client('rekognition')

    resp = requests.get(image)
    rekresp = {}
    resp_txt = str(resp)
    imgbytes = resp.content

    try:
        rekresp = rek.detect_faces(Image={'Bytes': imgbytes}, Attributes=['ALL'])
    except:
        #print("Couldn't upload image to AWS yet")
        pass

    return(rekresp, resp_txt)

def detect_labels(image, max_labels=10, min_confidence=90):
    """get labels (e.g House, car etc)"""
    rekognition = boto3.client("rekognition")
    resp = requests.get(image)
    imgbytes = resp.content
    label_response = rekognition.detect_labels(
        Image={'Bytes': imgbytes},
        MaxLabels=max_labels,
        MinConfidence=min_confidence,
    )
    return label_response['Labels']

def detect_moderation(image, max_labels=10, min_confidence=90):
    """https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rekognition.html"""
    resp = requests.get(image)
    imgbytes = resp.content
    moderation_response = client.detect_moderation_labels(
        Image={'Bytes': imgbytes},
        MaxLabels=max_labels,
        MinConfidence=min_confidence,
    )
    return moderation_response

def detect_text_detections(image):
    rekognition = boto3.client("rekognition")
    resp = requests.get(image)
    imgbytes = resp.content
    text_response = rekognition.detect_text(
        Image={'Bytes': imgbytes},
    )
    return text_response['TextDetections']

def on_connect(mq_client, userdata, flags, result_code):
    """The callback for when the client receives a CONNACK response from the server"""
    print(f'Connected with result code {result_code} - 0 = successful')
    serial = userdata['MV_SERIAL']
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    mq_client.subscribe(f'/merakimv/{serial}/0')

def on_message(client, userdata, msg):
    """When a PUBLISH message is received from the server, get a
    URL to analyse"""
    #triggers image analysis when incoming MQTT data is detected
    analyze()

def analyze():
    """periodially takes snap URL from Meraki, sends to AWS rekognition"""
    #initializing facecount
    facecount = 0
    counthappy = 0
    countsad = 0
    countangry = 0
    countsurprised  = 0
    countcalm = 0
    countfear = 0

    global loopcount

    if True:

        global emotiontext, averageage, agebuffer

        print("Request Snapshot URL")
        #get the URL of a snapshot from our camera
        snapshot_url = get_meraki_snapshots(session, API_KEY, NET_ID, None)
        #snapshoturl is ok.
        #assume the snapshot is not yet available for download:

        print("sending snapshot_url to AWS rekognition")


        resp_txt = "400"
        while ("400" in resp_txt) == True:
            #continually attempt to access snapshot URL
            #print("about to fetch image again...")
            rekresp, resp_txt = send_snap_to_aws(snapshot_url)


        #once the URL is available (resp_txt != 400), send to
        #AWS Rekognition and print results to stdout
        for face_detail in rekresp['FaceDetails']:
            #print Facial Analysis Results to stdout
            print('Facial Analysis: The detected face is between ' +
                  str(face_detail['AgeRange']['Low']) +
                  'and ' + str(face_detail['AgeRange']['High']) + ' years old')
            age = (((face_detail['AgeRange']['Low'])+(face_detail['AgeRange']['High']))/2)
            #fun factor below
            #age = age + 10
            
            #Print Emotion/Gender/Age to stdout
            emotional_state = max(face_detail['Emotions'], key=lambda x: x['Confidence'])
            emotion = emotional_state['Type']
            gender = (face_detail['Gender']['Value'])
            print(gender)
            print(emotion)
            print(age)
            #Publish Emotion/Gender/Age via MQTT to NodeRed

            client.publish("Age", age)
            client.publish("EmotionalState", emotion)
            client.publish("Gender", gender)
            
            #Saving Emotions to a String
            #emotionbuffer = str(emotiontext) + str(emotion)
            #emotiontext = emotionbuffer + " "

            #Saving Emotions to a LIST
            #emotionlist.append(emotion)

            #Found out that the Quickchart API wont accept more than 6 sentiments of a kind as a TEXT. Alternative is to use JSON to post feelings OR do some mathematics and post as TEXT.
            #MATHEMATICS approach below. 
            #Algorithm: count feelings first, then calculate how manytimes multiple of six each is. Not efficient, but helps achieve the goal.
            
            if emotion == "HAPPY":
               counthappy+=1
            if emotion == "SURPRISED":
               countsurprised+=1
            if emotion == "CALM":
               countcalm+=1
            if emotion == "FEAR":
               countfear+=1
            if emotion == "SAD":
               countsad+=1
            if emotion == "ANGRY":
               countangry+=1


            #Calculating Average age and number of people
            agebuffer = averageage + age
            averageage = agebuffer
            sumage = agebuffer + averageage
            facecount+=1
            loopcount+=1


        #Quantifying Emotions with 6 as maximum
        print("happy count = ", counthappy)
        print("suprised count = ", countsurprised)
        print("calm count = ", countcalm)
        print("fear count = ", countfear)
        print("sad count = ", countsad)
        print("angry count = ", countangry)

        #Now need to calculate how many multiples of 6 each sentiment has - this is needed in order to manually create a string that wont overflow sentiment count beyond 6 (which is the maximum amount the wordcloud supports w/o bugging). This hinders the growth size of the sentiments, but it allows for consistency.
        if counthappy > 0:

           emotiontext+= " HAPPY "
           print("added happy to string")

           if counthappy > 24:
               counthappy = 24

           multofsix = int(counthappy/6)
           for counter in range(0,multofsix):
               emotiontext+= " HAPPY "
               print("added happy to string")

        if countsad > 0:

           emotiontext+= " CALM "
           print("added sad_modifief to string")

           multofsix = int(countsad/6)
           for counter in range(0,multofsix):
               emotiontext+= " CALM "
               print("added sad to string")

        if countsurprised > 0:

           emotiontext+= " SURPRISED "
           print("added surprised to string")

           multofsix = int(countsurprised/6)
           for counter in range(0,multofsix):
               emotiontext+= " SURPRISED "
               print("added surprised to string")

        if countcalm > 0:


           if countcalm > 24:
               countcalm = 24

           emotiontext+= " CALM "
           print("added calm to string")

           multofsix = int(countcalm/6)
           for counter in range(0,multofsix):
               emotiontext+= " CALM "
               print("added calm to string")

        if countangry > 0:

           emotiontext+= " ANGRY "
           print("added angry to string")

           multofsix = int(countangry/6)
           for counter in range(0,multofsix):
               emotiontext+= " ANGRY "
               print("added angry to string")


        if countfear > 0:

           emotiontext+= " FEAR "
           print("added fear to string")

           multofsix = int(countfear/6)
           for counter in range(0,multofsix):
               emotiontext+= " FEAR "
               print("added fear to string")


        #METHOD 1
        #Wordcloud from Emotiontext to wordcloud using string
        wordcloudurl = "https://quickchart.io/wordcloud?text=" + str(emotiontext) +"&backgroundColor=black&case=upper&rotation=0"


        #REQUIRED - Publish wordcloud to NODERED
        print("wordcloudurl = ",wordcloudurl)
        client.publish("wordcloudurl", wordcloudurl)


        print("Averageage = ",round(averageage,2))
        print("Sumage = ", sumage)
        print("Faceount in the last image = ", facecount)
        client.publish("averageage", round(averageage,2))
        client.publish("facecount", facecount)

        #resetting Counters
        averageage = 0
        agebuffer = 0

        #Publish Object Detection via MQTT to NodeRed
        labels = []
        obj = 0
        objects_detected = detect_labels(snapshot_url)
        quantity_objects = len(objects_detected)
        print("objects_detected received")
        #Print to stdout all label names and confidence
        for label in objects_detected:
            #round "Confidence" to three decimal places
            truncated_confidence = str('%.3f' % round((label["Confidence"]), 3))
            detected_object = str("{Name}".format(**label))
            entry = detected_object + " - " + truncated_confidence +" %"
            labels.append(entry)
            label = ("Label" + str(obj))
            #print result to stdout
            #print(label + " " + entry)
            #publish to MQTT
            client.publish(label, entry)
            obj = obj+1
        client.publish("Snap", snapshot_url)
        while quantity_objects < 6:
            entry = " - "
            label = ("Label" + str(quantity_objects))
            quantity_objects = quantity_objects + 1
            client.publish(label, entry)
        #print("end of objects detected")

        #Print Text Detection via MQTT to NodeRed
        text_detections = []
        text_count= 0
        text_detected = detect_text_detections(snapshot_url)
        quantity_text_detections  = len(text_detections)
        print("text_detections received")
        for DetectedText in text_detected:
            truncated_confidence = str('%.3f' % round((DetectedText["Confidence"]),3))
            object = str("{DetectedText}".format(**DetectedText))
            text_entry = object + " - " + truncated_confidence +" %"
            #text_entry = str("{DetectedText} - {Confidence}%".format(**DetectedText))
            text_detections.append(text_entry)
            DetectedText = ("DetectedText" + str(text_count))
            #print(DetectedText + " " + text_entry)
            client.publish(DetectedText,text_entry)
            text_count = text_count + 1
        client.publish("Snap",snapshot_url)


        while quantity_text_detections  < 6:
            text_entry = " - "
            DetectedText = ("DetectedText" + str(quantity_text_detections ))
            quantity_text_detections  = quantity_text_detections  + 1
            client.publish(TextDetection, text_entry)
        print("end of text detected")


if __name__ == '__main__':

    (API_KEY, NET_ID, MV_SERIAL, SERVER_IP) = gather_credentials()
    USER_DATA = {
        'API_KEY': API_KEY,
        'NET_ID': NET_ID,
        'MV_SERIAL': MV_SERIAL,
        'SERVER_IP': SERVER_IP
    }
    session = requests.Session()
    #global emotiontext, emotionbuffer
    #emotiontext = " "
    #emotionbuffer = " "
    # Start MQTT client
    client = mqtt.Client()
    client.user_data_set(USER_DATA)
    #on connection to a MQTT broker:
    print("Attempting connection to MQTT Broker")
    client.on_connect = on_connect
    #when an MQTT message is received:
    client.on_message = on_message
    #specify the MQTT broker here
    client.connect(SERVER_IP, 1883, 100)

    emotiontext = str(" ")
    averageage = 0
    agebuffer = 0
    loopcount = 0
    print("Cleansing Dashboard...")
    client.publish("wordcloudurl", "https://quickchart.io/wordcloud?text= &backgroundColor=black&case=upper&rotation=0")
    client.publish("Snap", "https://lh6.googleusercontent.com/EKfcRcl5hbL3T3bdf-cnIMPIkphMv77g3fh8ubAIjPD0Kjpj7LweVMUm-WT9gEZbXOUTCHnKZEgH9CHaN4GmAVODcXiBYZlq80_Pd-AFTpIiBuELd4c1cYN2TzWzx7hQpQ=w1280")
    client.publish("averageage", 0)
    client.publish("facecount", 0)
    client.publish("Age", 0)
    client.publish("EmotionalState", "Waiting for Analysis")
    client.publish("Gender", "Waiting for Analysis")
    client.publish("About", "https://lh6.googleusercontent.com/EKfcRcl5hbL3T3bdf-cnIMPIkphMv77g3fh8ubAIjPD0Kjpj7LweVMUm-WT9gEZbXOUTCHnKZEgH9CHaN4GmAVODcXiBYZlq80_Pd-AFTpIiBuELd4c1cYN2TzWzx7hQpQ=w1280")

    client.loop_forever()
