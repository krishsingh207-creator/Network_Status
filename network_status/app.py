from flask import Flask, render_template, jsonify, request
import copy
import mysql.connector
import telnetlib
import threading
import time
import datetime
# from collections import defaultdict

app = Flask(__name__)

credentials = {
    'username' : 'ksingh',
    'username1': 'admin',
    'pass1': 'singh@kunal',
    'pass2': 'ckng@#%))PD',
    'pass3': 'ckng@#&%)PD',
    'pass4' : 'ckng@$^))PD',
    'enable': 'delDSL@6014'
}

devices = {
    'zy3500': [],
    'zy2210': [],
    'zy3750': [],
    'zy2220': [],
    'zy4600' : [[{'hostname':'172.30.82.238', 'device_id' : 179 , 'sysName' : '##c4#main_ring#sw82.238##mill'}]],
    'huawei' : [],
    'juniper' : [[{'hostname':'172.21.80.12', 'device_id' : 47 , 'sysName' : '#Mill#residence_main_ring_sw80.12#'}]]
}

cached_data = {}
removed_links = {}

DB_CONFIG = {
    'host': "192.168.10.177",
    'user': 'librenms',
    'password': 'deldsl@db',
    'database': 'librenmsdb'
}

def get_db_connection():
    while True:
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            return conn
        except mysql.connector.Error as err:
            print("Retrying DB connection due to:", err)

def run_query(query, db_name="librenmsdb"):
    db_cfg = DB_CONFIG.copy()
    db_cfg["database"] = db_name
    with mysql.connector.connect(**db_cfg) as conn:
        with conn.cursor(dictionary=True) as cursor:
            cursor.execute(query)
            return cursor.fetchall()

def fetch_alert_data():
    query = "SELECT port_id, device_id FROM alert_custom WHERE status=1 AND severity=2;"
    return run_query(query)

def reset_cache():
    global cached_data
    while True:
        time.sleep(2700)
        print("🔁 Resetting alert cache...")
        try:
            new_data = fetch_alert_data()
            if not isinstance(new_data, list) or not all(isinstance(item, dict) for item in new_data):
                print("⚠️ Invalid data format from fetch_alert_data:", new_data)
                continue
            cached_data = {
                (item['device_id'], item['port_id']): datetime.datetime.now()
                for item in new_data if 'device_id' in item and 'port_id' in item
            }
        except Exception as e:
            print("❌ Error in reset_cache:", e)

threading.Thread(target=reset_cache, daemon=True).start()

def fetch_devices():
    queries = {
        'zy3500': "SELECT hostname, device_id, sysName FROM devices WHERE sysDescr = 'ES3500-8PD' or sysDescr='MES3500-24F';",
        'zy2210': "SELECT hostname, device_id, sysName FROM devices WHERE sysDescr = 'GS2210-8';",
        'zy3750': "SELECT hostname, device_id, sysName FROM devices WHERE hardware = 'ZyXEL MGS3750-28F Switch' or hostname = '172.30.87.19' or hostname = '172.30.82.66' or hostname = '172.30.82.30' or hostname = '172.30.82.224' or hostname = '172.30.82.235' or hostname = '172.30.80.10';",
        'zy2220': "SELECT hostname, device_id, sysName from devices WHERE hardware = 'XGS2220-30F';",
        'huawei': "SELECT hostname, device_id, sysName FROM devices WHERE sysDescr LIKE 'S5735%' OR sysDescr LIKE 'S5720%';"
    }
    for model, query in queries.items():
        try:
            result = run_query(query, db_name="librenmsdb")
            devices[model] = [result]
        except Exception as e:
            print(f"⚠️ Failed to fetch {model} devices:", e)

def schedule_device_fetch():
    while True:
        print("🔄 Updating device list...")
        fetch_devices()
        time.sleep(86400)

threading.Thread(target=schedule_device_fetch, daemon=True).start()

def alertStatus():
    from collections import defaultdict

    device_port_map = defaultdict(list)

    for (device_id, port_id), timestamp in cached_data.items():
        device_port_map[device_id].append(port_id)

    filtered_data = {}

    for model, device_lists in devices.items():
        filtered_lists = []
        for device_list in device_lists:
            new_list = []
            for device in device_list:
                if device['device_id'] in device_port_map:
                    for port_id in device_port_map[device['device_id']]:
                        new_dev = device.copy()
                        new_dev['port_id'] = port_id
                        new_list.append(new_dev)
            if new_list:
                filtered_lists.append(new_list)
        if filtered_lists:
            filtered_data[model] = filtered_lists

    for model, device_lists in filtered_data.items():
        for device_list in device_lists:
            for device in device_list:
                hostname = device['hostname']
                port_id = device.get('port_id')

                # Fetch ifDescr/ifIndex
                port_info = run_query(f"SELECT ifDescr, ifIndex FROM ports WHERE port_id = {port_id};")
                if not port_info:
                    print(f"⚠️ Skipping {hostname} due to missing port info for port_id {port_id}")
                    continue
                device['port_number'] = port_info
                ifDescr = port_info[0]['ifDescr']
                ifIndex = port_info[0]['ifIndex']

                try:
                    print(f"🔌 Connecting to {hostname} ({model})...")

                    tn = telnetlib.Telnet(hostname, timeout=10)

                    # --- Login block ---
                    if model in ['zy3500', 'zy2210', 'zy2220', 'zy4600']:
                        tn.read_until(b"name: ")
                        tn.write(credentials['username1'].encode("ascii") + b"\n")
                        tn.read_until(b'Password: ')
                        if model == 'zy4600':
                            tn.write(credentials['pass4'].encode('ascii') + b"\n")
                        else:
                            tn.write(credentials['pass2'].encode('ascii') + b"\n")
                        tn.read_until(b'##')

                        tn.write(f"show interfaces transceiver {ifIndex}\n".encode())
                        time.sleep(3)
                        output = tn.read_very_eager().decode('ascii', errors='ignore')

                        rx_power = "N/A"
                        for line in output.splitlines():
                            if "RX Power(dbm)" in line:
                                for val in line.split():
                                    try:
                                        rx_power_val = float(val)
                                        rx_power = f"{rx_power_val} dBm"
                                        break
                                    except:
                                        continue
                                break

                        tn.write(f"show interface {str(ifIndex).zfill(2)}\n".encode())
                        time.sleep(3)
                        status_output = tn.read_very_eager().decode('ascii', errors='ignore')

                        link_status = "N/A"
                        errors = "N/A"
                        for line in status_output.splitlines():
                            if "Link" in line:
                                link_status = line.split(":")[-1].strip()
                            elif "Errors" in line:
                                errors = line.split(":")[-1].strip()

                    elif model == 'zy3750':
                        port_num = ifDescr
                        if 'e' not in port_num:
                            print(f"⚠️ Skipping {hostname} due to invalid ifDescr: {port_num}")
                            continue
                        ifIndex = port_num.split('e')[1]

                        tn.read_until(b"Username")
                        tn.write(credentials['username'].encode("ascii") + b"\n")
                        tn.read_until(b"Password")
                        tn.write(credentials['pass1'].encode("ascii") + b"\n")
                        tn.read_until(b">")
                        tn.write(b"enable\n")
                        tn.read_until(b"#")

                        tn.write(f"show interface sfp e {ifIndex}\n".encode())
                        time.sleep(1)
                        tn.write(b" ")
                        time.sleep(1)
                        output = tn.read_very_eager().decode('ascii', errors='ignore')

                        rx_power = "N/A"
                        for line in output.splitlines():
                            if "RX Power(dBM)" in line:
                                rx_power = line.split(":")[1].strip() + " dBm"
                                break

                        tn.write(f"show interface e {ifIndex}\n".encode())
                        time.sleep(3)
                        output = tn.read_very_eager().decode('ascii', errors='ignore')

                        link_status = "N/A"
                        if "port link is down" in output.lower():
                            link_status = "Down"
                        elif "port link is up" in output.lower():
                            link_status = "UP"
                        errors = "N/A"

                    elif model == 'huawei':
                        tn.read_until(b"Username:")
                        tn.write(credentials['username'].encode("ascii") + b"\n")
                        tn.read_until(b"Password:")
                        tn.write(credentials['pass1'].encode("ascii") + b"\n")
                        tn.read_until(b'>')
                        tn.write(b"super\n")
                        tn.read_until(b"Password:")
                        tn.write(credentials['enable'].encode("ascii") + b"\n")
                        time.sleep(1)

                        tn.write(f"display transceiver interface {ifDescr} verbose\n".encode())
                        time.sleep(1)
                        tn.write(b" ")
                        time.sleep(1)
                        output = tn.read_very_eager().decode('ascii', errors='ignore')

                        rx_power = "N/A"
                        for line in output.splitlines():
                            if "RX Power(dBM)" in line:
                                rx_power = line.split(":")[1].strip() + " dBm"
                                break

                        tn.write(f"display interface {ifDescr}\n".encode())
                        time.sleep(1)
                        tn.write(b" ")
                        time.sleep(1)
                        output = tn.read_very_eager().decode('ascii', errors='ignore')

                        link_status = "N/A"
                        errors = "N/A"
                        for line in output.splitlines():
                            if "current state" in line.lower():
                                link_status = "UP" if "up" in line.lower() else "Down"
                            if "Total Error" in line:
                                errors = line.split(":")[1].strip()

                    elif model == 'juniper':
                        tn.read_until(b"login:")
                        tn.write(credentials['username'].encode("ascii") + b"\n")
                        tn.read_until(b"Password:")
                        tn.write(credentials['pass1'].encode("ascii") + b"\n")
                        tn.read_until(b">")

                        tn.write(f"show interfaces diagnostics optics {ifDescr}\n".encode())
                        time.sleep(2)
                        output = tn.read_very_eager().decode('ascii', errors='ignore')

                        rx_power = "N/A"
                        for line in output.splitlines():
                            if "Receiver signal average optical power" in line:
                                try:
                                    rx_power = line.split(":")[1].split("/")[1].strip()
                                except:
                                    pass
                                break

                        tn.write(f"show interfaces {ifDescr} extensive\n".encode())
                        time.sleep(2)
                        output = tn.read_very_eager().decode('ascii', errors='ignore')

                        link_status = "N/A"
                        input_errors = "0"
                        for line in output.splitlines():
                            if "Physical link is" in line:
                                link_status = "UP" if "Up" in line else "Down"
                            if "Input errors:" in line:
                                input_errors = line.split("Errors:")[1].split(",")[0].strip()

                        errors = input_errors

                    # Save result in device dictionary
                    device['Rx_optical_power'] = rx_power
                    device['Link_status'] = link_status
                    device['Errors'] = errors

                    tn.write(b"exit\n")
                    tn.close()

                except Exception as e:
                    print(f"❌ Error connecting to {hostname} ({model}): {e}")

    return filtered_data


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_data')
def get_data():
    now = datetime.datetime.now()
    expired = [pid for pid, ts in removed_links.items() if now - ts > datetime.timedelta(minutes=45)]
    for pid in expired:
        del removed_links[pid]

    data = copy.deepcopy(alertStatus())

    for vendor in list(data):
        new_lists = []
        for device_list in data[vendor]:
            filtered_list = [d for d in device_list if str(d['port_id']) not in removed_links]
            if filtered_list:
                new_lists.append(filtered_list)
        if new_lists:
            data[vendor] = new_lists
        else:
            del data[vendor]

    return jsonify(data)

@app.route('/remove_link', methods=['POST'])
def remove_link():
    port_id = request.json.get('port_id')
    removed_links[port_id] = datetime.datetime.now()
    return jsonify({'status': 'removed'})

@app.route('/check_optical_power', methods=['POST'])
def check_optical_power():
    data = request.json
    hostname = data.get('hostname')
    model = data.get('model')
    ifIndex = data.get('ifIndex')

    try:
        tn = telnetlib.Telnet(hostname, timeout=10)

        rx_power = "N/A"

        if model in ['zy3500', 'zy2210', 'zy2220', 'zy4600']:
            tn.read_until(b"name: ")
            tn.write(credentials['username1'].encode("ascii") + b"\n")
            tn.read_until(b'Password: ')
            if model == 'zy4600':
                tn.write(credentials['pass4'].encode('ascii') + b"\n")
            else:
                tn.write(credentials['pass2'].encode('ascii') + b"\n")

            tn.read_until(b'##')
            tn.write(f"show interfaces transceiver {ifIndex}\n".encode())
            time.sleep(3)
            output = tn.read_very_eager().decode('ascii', errors='ignore')
            # print(f"[DEBUG] Raw Telnet Output:\n{output}")


            for line in output.splitlines():
                if "RX Power(dbm)" in line:
                    for val in line.split():
                        try:
                            rx_power = f"{float(val)} dBm"
                            break
                        except:
                            continue
                    break
        elif model == 'zy3750':
            tn.read_until(b"Username")
            tn.write(credentials['username'].encode("ascii") + b"\n")
            tn.read_until(b"Password")
            tn.write(credentials['pass1'].encode("ascii") + b"\n")
            tn.read_until(b">")
            tn.write(b"enable\n")
            tn.read_until(b"#")

            # ✅ Strip extra 'e' prefix if present in ifIndex (e.g. 'e0/0/23')
            sanitized_ifIndex = ifIndex.lower().lstrip('e')  # becomes '0/0/23'

            tn.write(f"show interface sfp e {sanitized_ifIndex}\n".encode())
            time.sleep(1)
            tn.write(b" ")
            time.sleep(1)
            output = tn.read_very_eager().decode('ascii', errors='ignore')
            # print(f"[DEBUG] Raw Telnet Output:\n{output}")

            rx_power = "N/A"
            for line in output.splitlines():
                if "RX Power(dBM)" in line:
                    parts = line.split(":")
                    if len(parts) == 2:
                        rx_power = parts[1].strip() + " dBm"
                    break


        elif model == 'huawei':
            tn.read_until(b"Username:")
            tn.write(credentials['username'].encode('ascii') + b"\n")
            tn.read_until(b"Password:")
            tn.write(credentials['pass1'].encode('ascii') + b"\n")
            tn.read_until(b">")
            tn.write(b"super\n")
            tn.read_until(b"Password:")
            tn.write(credentials['enable'].encode('ascii') + b"\n")
            time.sleep(1)

            tn.write(f"display transceiver interface {ifIndex} verbose\n".encode())
            time.sleep(1)
            tn.write(b" ")
            time.sleep(1)
            output = tn.read_very_eager().decode('ascii', errors='ignore')
            # print(f"[DEBUG] Raw Telnet Output:\n{output}")


            for line in output.splitlines():
                if "RX Power(dBM)" in line:
                    parts = line.split(":")
                    if len(parts) == 2:
                        rx_power = parts[1].strip() + " dBm"
                    break

        elif model == 'juniper':
            tn.read_until(b"login:")
            tn.write(credentials['username'].encode('ascii') + b"\n")
            tn.read_until(b"Password:")
            tn.write(credentials['pass1'].encode('ascii') + b"\n")
            tn.read_until(b">")

            tn.write(f"show interfaces diagnostics optics {ifIndex}\n".encode())
            time.sleep(2)
            output = tn.read_very_eager().decode('ascii', errors='ignore')
            # print(f"[DEBUG] Raw Telnet Output:\n{output}")


            for line in output.splitlines():
                if "Receiver signal average optical power" in line:
                    try:
                        rx_power = line.split(":")[1].split("/")[1].strip()
                    except:
                        pass
                    break

        tn.write(b"exit\n")
        tn.close()

        return jsonify({"status": "success", "Rx_optical_power": rx_power})

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route('/refresh', methods=['POST'])
def refresh_data():
    global cached_data
    try:
        new_data = fetch_alert_data()
        now = datetime.datetime.now()
        for entry in new_data:
            key = (entry['device_id'], entry['port_id'])
            cached_data[key] = now
        threshold = now - datetime.timedelta(minutes=45)
        cached_data = {k: v for k, v in cached_data.items() if v >= threshold}
        return jsonify({"status": "success"})
    except Exception as e:
        print(f"❌ Error in /refresh: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
