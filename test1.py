from dcim.models import DeviceType
from extras.scripts import Script, ObjectVar

class DeviceTypeTest(Script):
    class Meta:
        name = "Test DeviceType"

    dt = ObjectVar(
        model=DeviceType,
        label="Pick Device Type"
    )

    def run(self, data, commit):
        return f"Selected: {data['dt']}"
