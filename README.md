[SaveEcoBot](https://www.saveecobot.com/en) is a great Ukrainian eco-project.
[Home Assistant](https://www.home-assistant.io/) is an amazing home automation system

This code snippet adds SaveEcoBot API information (radiation sensor only) to Home Assistant for the capital of Ukraine 🇺🇦

run test, we try, we check

```yaml
sensor:
  - platform: radiation_sensor
    name: "Kyiv Radiation Level"
```
