import csv
import pynetbox
import urllib3
import ipaddress
import os
from dotenv import load_dotenv
load_dotenv()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

NETBOX_URL = os.getenv("server")  # Replace with your NetBox URL
NETBOX_TOKEN = os.getenv("token")  # Replace with your NetBox API token

INPUT_CSV = "data.csv"
FAILED_CSV = "failed_devices.csv"

nb = pynetbox.api(NETBOX_URL, token=NETBOX_TOKEN)
nb.http_session.verify = False

# Function to get required object or return None
def get_required(api_endpoint, name, label):
    obj = api_endpoint.get(name=name)
    if obj is None:
        print(f"[WARNING] {label} '{name}' not found.")
    return obj

failed_rows = []

with open(INPUT_CSV, newline='') as csvfile:
    reader = csv.DictReader(csvfile, delimiter=',')

    fieldnames = reader.fieldnames  # Save for failed CSV output

    for row in reader:
        row = {k.strip(): v.strip() for k, v in row.items()}

        try:
            # Lookup required objects
            manufacturer = get_required(nb.dcim.manufacturers, row["manufacturer"], "Manufacturer")
            device_type = nb.dcim.device_types.get(model=row["device_type"], manufacturer_id=manufacturer.id) if manufacturer else None
            role = get_required(nb.dcim.device_roles, row["role"], "Device Role")
            site = get_required(nb.dcim.sites, row["site"], "Site")
            tenant = nb.tenancy.tenants.get(name=row["tenant"]) if row["tenant"] else None

            if not manufacturer or not device_type or not role or not site:
                raise ValueError(f"Missing reference: "
                                f"{'manufacturer ' if not manufacturer else ''}"
                                f"{'device_type ' if not device_type else ''}"
                                f"{'role ' if not role else ''}"
                                f"{'site ' if not site else ''}".strip())


            # Create or get device
            device = nb.dcim.devices.get(name=row["name"])
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
                print(f"[INFO] Created device: {row['name']}")
            else:
                print(f"[INFO] Device already exists: {row['name']}")

            # Handle IP
            if row["address"]:
                if nb.ipam.ip_addresses.get(address=row["address"]):
                    print(f"[INFO] IP address already exists: {row['address']}")
                    continue

                interface = nb.dcim.interfaces.get(device_id=device.id, name="LAN")
                if not interface:
                    interface = nb.dcim.interfaces.create({
                        "device": device.id,
                        "name": "LAN",
                        "type": "1000base-t"
                    })
                    print(f"[INFO] Created interface 'LAN' for {row['name']}")

                ip_address = row["address"] if "/" in row["address"] else f"{row['address']}/24"

                ip_data = {
                    "address": ip_address,
                    "description": row['mac'],
                    "assigned_object_type": "dcim.interface",
                    "assigned_object_id": interface.id,
                    "dns_name": row["dns_name"],
                    "status": "active"
                }

                ip_obj = nb.ipam.ip_addresses.create(ip_data)
                print(f"[INFO] Created IP address {row['address']} for {row['name']}")

                ip_version = ipaddress.ip_interface(row["address"]).version
                primary_field = "primary_ip4" if ip_version == 4 else "primary_ip6"
                device.update({primary_field: ip_obj.id})
                print(f"[INFO] Set {row['address']} as primary IP for {row['name']}")

        except Exception as e:
            print(f"[ERROR] {e}. Skipping row for device: {row.get('name', '[unknown]')}")
            failed_rows.append(row)

# Write failed rows to a CSV file
if failed_rows:
    with open(FAILED_CSV, mode='w', newline='') as failed_file:
        writer = csv.DictWriter(failed_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(failed_rows)
    print(f"[INFO] Failed device entries written to: {FAILED_CSV}")
else:
    print("[INFO] All devices processed successfully.")