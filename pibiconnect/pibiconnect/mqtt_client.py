import paho.mqtt.client as mqtt
import frappe
from frappe.utils.background_jobs import enqueue
import json

# MQTT settings
MQTT_BROKER = frappe.conf.get("mqtt_gateway")
MQTT_PORT = int(frappe.conf.get("mqtt_port"))
MQTT_USERNAME = frappe.conf.get("mqtt_user")
MQTT_PASSWORD = frappe.conf.get("mqtt_secret")
MQTT_TOPICS = ["#"]  # List of topics to subscribe to

client = None  # Reference to the MQTT client

# Callback when the client receives a connection response from the server
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        frappe.logger().info("Connected to MQTT broker")
        for topic in MQTT_TOPICS:
            client.subscribe(topic)
            frappe.logger().info(f"Subscribed to topic: {topic}")
    else:
        frappe.logger().error(f"Failed to connect to MQTT broker, return code {rc}")

# Callback when a PUBLISH message is received from the server
def on_message(client, userdata, msg):
    message = msg.payload.decode()
    frappe.logger().info(f"Received message: {message} on topic: {msg.topic}")
    frappe.publish_realtime(event='mqtt_message', message={'topic': msg.topic, 'payload': message})
    frappe.logger().info(f"Published message to realtime: {message}")

def on_disconnect(client, userdata, rc):
    if rc != 0:
        frappe.logger().error(f"Unexpected disconnection. Return code: {rc}")
    else:
        frappe.logger().info("MQTT client disconnected")

def setup_mqtt_client():
    global client
    client = mqtt.Client()
    if MQTT_USERNAME and MQTT_PASSWORD:
      client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

def mqtt_client_loop():
    global client
    if client is None:
        setup_mqtt_client()
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        frappe.logger().error(f"Error connecting to MQTT broker: {e}")

@frappe.whitelist()
def start_mqtt():
    global client
    if client:
        frappe.logger().info("MQTT client already running")
        return {'status': 'already running'}
    
    try:
        job = enqueue('pibiconnect.pibiconnect.mqtt_client.mqtt_client_loop', timeout=0, queue='long', job_name='mqtt_start_job')
        return {'status': 'started', 'job_id': job.id}
    except Exception as e:
        frappe.logger().error(f"Error starting MQTT client: {str(e)}")
        return {'status': 'error', 'message': str(e)}

@frappe.whitelist()
def stop_mqtt(job_name=None):
    global client
    if job_name:
        try:
            # Check if the table exists before attempting to delete
            table_exists = frappe.db.sql(
                "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = 'tabRQ Job'",
                as_list=True
            )[0][0]
            
            if table_exists:
                frappe.db.sql("DELETE FROM `tabRQ Job` WHERE job_name=%s", (job_name,))
                frappe.db.commit()
            else:
                frappe.logger().warning("Table 'tabRQ Job' does not exist. Skipping job deletion.")
        except Exception as e:
            frappe.logger().error(f"Error deleting job from database: {str(e)}")
    
    if client:
        try:
            client.loop_stop()
            client.disconnect()
            frappe.logger().info("MQTT client disconnected")
        except Exception as e:
            frappe.logger().error(f"Error disconnecting MQTT client: {str(e)}")
        finally:
            client = None
    
    return {'status': 'stopped'}
    
@frappe.whitelist()
def status():
    global client
    is_connected = client is not None and client.is_connected() if client else False
    return {'status': 'running' if is_connected else 'stopped'}

def setup_mqtt_client_args(data):
    global client
    client = mqtt.Client()
    if data.get('username') and data.get('password'):
      client.username_pw_set(data['username'], data['password'])
    client.user_data_set({'topics': data['topics_table']})
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    if data.get('validate_cert'):
        client.tls_set()  # Add appropriate arguments if necessary

def mqtt_client_loop():
    global client
    if client is None:
        setup_mqtt_client()
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        frappe.logger().error(f"Error connecting to MQTT broker: {e}")
        client = None

@frappe.whitelist()
def start_mqtt_args(data):
    if isinstance(data, str):
        data = json.loads(data)  # Ensure the data is deserialized
    job = enqueue(
        'pibiconnect.pibiconnect.mqtt_client.mqtt_client_loop_args',
        data=json.dumps(data),  # Serialize the data as JSON
        timeout=0,
        queue='long',
        job_name='mqtt_start_job'
    )
    return {'status': 'started', 'job_id': job.id}

@frappe.whitelist()
def ensure_mqtt_running(job_id=None):
    if job_id:
        rq_job = frappe.get_all(
            "RQ Job",
            filters={"job_id": job_id},
            fields=["name", "status"]
        )
        if rq_job and rq_job[0].status == "started":
            return {'status': 'running'}
        else:
            start_mqtt()
            return {'status': 'restarted'}
    else:
        start_mqtt()
        return {'status': 'restarted'}