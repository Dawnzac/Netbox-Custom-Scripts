from extras.scripts import Script, StringVar

class HelloWorld(Script):
    class Meta:
        name = "Hello Script"
        description = "This is a test script to make sure scripts run"

    your_name = StringVar(
        description="What is your name?"
    )

    def run(self, data, commit):
        return f"Hello, {data['your_name']}!"
