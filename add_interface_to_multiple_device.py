from dcim.models import DeviceType, InterfaceTemplate
from dcim.choices import InterfaceTypeChoices
from extras.scripts import Script, ObjectVar, StringVar, BooleanVar

class AddInterfaceTemplate(Script):
    class Meta:
        name = "Add Interface to DeviceType"

    device_type = ObjectVar(
        model=DeviceType,
        label="Device Type"
    )

    interface_name = StringVar(
        label="Interface Name"
    )

    interface_type = StringVar(
        label="Interface Type",
        choices=InterfaceTypeChoices.choices  # <-- dynamic choices here
    )

    enabled = BooleanVar(
        label="Enabled",
        default=True
    )

    def run(self, data, commit):
        dt = data["device_type"]

        if InterfaceTemplate.objects.filter(device_type=dt, name=data["interface_name"]).exists():
            return f"Interface '{data['interface_name']}' already exists on {dt}"

        iface = InterfaceTemplate(
            device_type=dt,
            name=data["interface_name"],
            type=data["interface_type"],
            enabled=data["enabled"]
        )

        if commit:
            iface.save()
            return f"Added interface '{iface.name}' to {dt}"
        else:
            return f"(Dry run) Would add interface '{iface.name}' to {dt}"
