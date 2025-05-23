import csv
import pynetbox
import urllib3
import ipaddress
import os
import logging

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from dotenv import load_dotenv
load_dotenv()

NETBOX_URL = os.getenv("server")  # Replace with your NetBox URL
NETBOX_TOKEN = os.getenv("token")  # Replace with your NetBox API token

INPUT_CSV = "data.csv"
FAILED_CSV = "failed_devices.csv"
SKIPPED_CSV = "skipped_devices.csv"
LOG_FILE = "device_import.log"

logging.basicConfig(
    filename=LOG_FILE,
    filemode='a',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
nb.http_session.verify = False

def log_print(msg, level="info"):
    print(msg)
    getattr(logging, level)(msg)

def get_required(api_endpoint, name, label):
    obj = api_endpoint.get(name=name)
    if obj is None:
        log_print(f"[WARNING] {label} '{name}' not found.")
    return obj

failed_rows = []
skipped_rows = []

with open(INPUT_CSV, newline='') as csvfile:
    reader = csv.DictReader(csvfile, delimiter=',')
    fieldnames = reader.fieldnames

    for row in reader:
        row = {k.strip(): v.strip() for k, v in row.items()}

        try:
            manufacturer = get_required(nb.dcim.manufacturers, row["manufacturer"], "Manufacturer")
            device_type = nb.dcim.device_types.get(model=row["device_type"], manufacturer_id=manufacturer.id) if manufacturer else None
            role = get_required(nb.dcim.device_roles, row["role"], "Device Role")
            site = get_required(nb.dcim.sites, row["site"], "Site")
            tenant = nb.tenancy.tenants.get(name=row["tenant"]) if row["tenant"] else None

            if not all([manufacturer, device_type, role, site]):
                raise ValueError("Missing required reference (manufacturer, device_type, role, or site)")

            ip_address = row["address"]
            if ip_address and "/" not in ip_address:
                ip_address += "/24"
            device = nb.dcim.devices.get(name=row["name"])
            ip_obj = nb.ipam.ip_addresses.get(address=ip_address) if ip_address else None

            if not device:
                device = nb.dcim.devices.create({
                    "name": row["name"],
                    "device_type": device_type.id,
                    "role": role.id,
                    "site": site.id,
                    "status": row["status"],
                    "serial": row["serial"],
                    "comments": row["comments"],
                    "tenant": tenant.id if tenant else None,
                    "description": row["mac"]
                })
                log_print(f"[INFO] Created device: {row['name']}")
            else:
                log_print(f"[INFO] Device already exists: {row['name']}")

            # Link device to inventory asset if serial matches
            try:
                assets = nb.http_session.get(
                    f"{NETBOX_URL}/api/plugins/inventory/assets/",
                    headers={"Authorization": f"Token {NETBOX_TOKEN}"},
                    params={"serial": row["serial"]},
                )
                if assets.status_code == 200:
                    asset_data = assets.json().get("results", [])
                    if asset_data:
                        asset = asset_data[0]
                        if asset.get("device") is None:
                            nb.http_session.patch(asset["url"],
                                                  headers={"Authorization": f"Token {NETBOX_TOKEN}"},
                                                  json={"device": device.id})
                            log_print(f"[INFO] Linked asset with serial {row['serial']} to device {row['name']}")
                        else:
                            log_print(f"[INFO] Asset with serial {row['serial']} already assigned. Skipping asset assignment.")
                    else:
                        log_print(f"[WARNING] Asset with serial {row['serial']} not found.")
                else:
                    log_print(f"[WARNING] Failed to query asset for serial {row['serial']}. HTTP {assets.status_code}")
            except Exception as e:
                log_print(f"[WARNING] Could not link asset to device {row['name']}: {e}")

            if ip_address:
                interface = nb.dcim.interfaces.get(device_id=device.id, name="WAN")
                if not interface:
                    interface = nb.dcim.interfaces.create({
                        "device": device.id,
                        "name": "WAN",
                        "type": "1000base-t"
                    })
                    log_print(f"[INFO] Created interface 'LAN' for {row['name']}")

                if not ip_obj:
                    ip_obj = nb.ipam.ip_addresses.create({
                        "address": ip_address,
                        "description": row["mac"],
                        "assigned_object_type": "dcim.interface",
                        "assigned_object_id": interface.id,
                        "dns_name": row["name"],
                        "status": "active"
                    })
                    log_print(f"[INFO] Created and assigned IP {ip_address} to {row['name']}")

                    if ip_obj and ip_obj.assigned_object_id == interface.id:
                        ip_version = ipaddress.ip_interface(ip_address).version
                        primary_field = "primary_ip4" if ip_version == 4 else "primary_ip6"
                        device.update({primary_field: ip_obj.id})
                        log_print(f"[INFO] Set {ip_address} as primary IP for {row['name']}")

                else:
                    if ip_obj.assigned_object_id is None:
                        ip_obj.update({
                            "assigned_object_type": "dcim.interface",
                            "assigned_object_id": interface.id
                        })
                        log_print(f"[INFO] Assigned existing IP {ip_address} to {row['name']}")

                        if ip_obj and ip_obj.assigned_object_id == interface.id:
                            ip_version = ipaddress.ip_interface(ip_address).version
                            primary_field = "primary_ip4" if ip_version == 4 else "primary_ip6"
                            device.update({primary_field: ip_obj.id})
                            log_print(f"[INFO] Set {ip_address} as primary IP for {row['name']}")

                    else:
                        log_print(f"[INFO] IP {ip_address} already exists and is assigned. Skipping IP binding.")
                        row["reason"] = f"IP {ip_address} already exists and is assigned"
                        skipped_rows.append(row)

        except Exception as e:
            log_print(f"[ERROR] {e}. Skipping row for device: {row.get('name', '[unknown]')}")
            row["reason"] = str(e)
            failed_rows.append(row)

if failed_rows:
    with open(FAILED_CSV, mode='w', newline='') as failed_file:
        writer = csv.DictWriter(failed_file, fieldnames=fieldnames + ["reason"])
        writer.writeheader()
        writer.writerows(failed_rows)
    log_print(f"[INFO] Failed device entries written to: {FAILED_CSV}")

if skipped_rows:
    with open(SKIPPED_CSV, mode='w', newline='') as skipped_file:
        writer = csv.DictWriter(skipped_file, fieldnames=fieldnames + ["reason"])
        writer.writeheader()
        writer.writerows(skipped_rows)
    log_print(f"[INFO] Skipped device entries written to: {SKIPPED_CSV}")
else:
    log_print("[INFO] All devices and IPs processed successfully.")