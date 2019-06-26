import machine
import utime

from utils import MQTTWriter, Slack, Ubidots, current_time, force_garbage_collect


class MoistureSensor(object):
    def __init__(self, adc_pin, config_dict):
        """
        Sensor calibration
        ######################
        This was determined by placing the sensor in&out of water, and reading the ADC value
        Note: That this values might be unique to individual sensors, ie your mileage may vary
        dry air = 841 (0%) eq 0v ~ 0
        water = 470 (100%) eq 3.3v ~ 1023
        Expects a dict:
            config_dict = {"moisture_sensor_cal": {"dry": 841, "wet": 470}
        """
        self.adc_pin = adc_pin
        self.config = config_dict
        self.setup_adc
        self._slack = None
        self.ubidots = Ubidots(
            self.config["ubidots"]["token"], self.config["ubidots"]["device"]
        )
        # self._mqtt = None

    @property
    def setup_adc(self):
        self.adc = machine.ADC(self.adc_pin)

    @property
    def slack(self):
        """Slack message init"""
        config = self.config["slack_auth"]
        self._slack = Slack(config["app_id"], config["secret_id"], config["token"])
        return self._slack.slack_it

    # @property
    # def mqtt(self):
    #     host = self.config["MQTT_config"]["Host"]
    #     self._mqtt = MQTTWriter(host)
    #     return self._mqtt

    def average(self, samples):
        ave = sum(samples, 0.0) / len(samples)
        return ave if ave > 0 else 0

    def read_samples(self, n_samples=10, rate=0.5):
        sampled_adc = []
        for i in range(n_samples):
            sampled_adc.append(self.adc.read())
            utime.sleep(rate)
        force_garbage_collect()
        return sampled_adc

    def adc_map(self, current_val, fromLow, fromHigh, toLow, toHigh):
        """
        Re-maps a number from one range to another.
        That is, a value of 'fromLow' would get mapped to 'toLow',
        a value of 'fromHigh' to 'toHigh', values in-between to values in-between, etc.

        Does not constrain values to within the range, because out-of-range values are
        sometimes intended and useful.

        y = adc_map(x, 1, 50, 50, 1);

        The function also handles negative numbers well, so that this example

        y = adc_map(x, 1, 50, 50, -100);

        is also valid and works well.

        The adc_map() function uses integer math so will not generate fractions,
        when the math might indicate that it should do so.
        Fractional remainders are truncated, and are not rounded or averaged.

        Parameters
        ----------
        value: the number to map.
        fromLow: the lower bound of the value’s current range.
        fromHigh: the upper bound of the value’s current range.
        toLow: the lower bound of the value’s target range.
        toHigh: the upper bound of the value’s target range.

        Adapted from https://www.arduino.cc/reference/en/language/functions/math/map/
        """

        return (current_val - fromLow) * (toHigh - toLow) / (fromHigh - fromLow) + toLow

    def soil_sensor_check(self):
        try:
            samples = self.read_samples()
            sampled_adc = self.average(samples)
            SoilMoistPerc = self.adc_map(
                sampled_adc,
                self.config["moisture_sensor_cal"]["dry"],
                self.config["moisture_sensor_cal"]["wet"],
                0,
                100,
            )
            self.ubidots.post_request({"soil_moisture": SoilMoistPerc})
            if SoilMoistPerc <= self.config["moisture_sensor_cal"].get("Threshold", 15):
                msg = "Soil Moisture Sensor: %.2f%% \t %s" % (
                    SoilMoistPerc,
                    current_time(),
                )
                self.slack(msg)
                print(msg)
            elif SoilMoistPerc <= 50:
                msg = "Soil Moisture is at 50% You should probably Water the plant."
                self.slack(msg)
                print(msg)
            force_garbage_collect()
        except Exception as exc:
            print("Exception: %s", exc)

    def run_timer(self, secs=60):
        while True:
            self.soil_sensor_check()
            utime.sleep(secs)
        print("Timer Initialised, callback will be ran every %s seconds!!!" % secs)
