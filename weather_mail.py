import os

# =============================================================================
#  CONFIGURATION SECTION
#  Reads from environment variables / GitHub Secrets if present,
#  otherwise falls back to the configured default values below.
# =============================================================================
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "").strip()
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "").strip()
APP_PASSWORD = os.environ.get("APP_PASSWORD", "").strip()
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL", "").strip()
CITY = os.environ.get("CITY", "").strip() or "Toronto"
COUNTRY_CODE = os.environ.get("COUNTRY_CODE", "").strip() or "CA"
# =============================================================================
#  END OF CONFIGURATION SECTION  -  Do not edit below this line
# =============================================================================

import json
import smtplib
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

API_URL = "https://api.openweathermap.org/data/2.5/weather"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465


def check_configuration():
    """Make sure the placeholder values were replaced."""
    problems = []
    if "PASTE_MY" in OPENWEATHER_API_KEY or not OPENWEATHER_API_KEY.strip():
        problems.append("OPENWEATHER_API_KEY has not been filled in.")
    if "MY_EMAIL@gmail.com" in SENDER_EMAIL or not SENDER_EMAIL.strip():
        problems.append("SENDER_EMAIL has not been filled in.")
    if "MY_GMAIL_APP_PASSWORD" in APP_PASSWORD or not APP_PASSWORD.strip():
        problems.append("APP_PASSWORD has not been filled in.")
    if "MY_EMAIL@gmail.com" in RECEIVER_EMAIL or not RECEIVER_EMAIL.strip():
        problems.append("RECEIVER_EMAIL has not been filled in.")
    if problems:
        print("ERROR: Please edit the configuration section at the top of the file:")
        for p in problems:
            print("  - " + p)
        return False
    return True


def degrees_to_compass(degrees):
    """Convert wind degrees (0-360) to a compass direction like 'NW'."""
    directions = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    index = int((degrees % 360) / 22.5 + 0.5) % 16
    return f"{directions[index]} ({degrees:.0f}°)"


def fetch_weather():
    """Call the OpenWeather API and return the parsed JSON data (or None on failure)."""
    params = urllib.parse.urlencode({
        "q": f"{CITY},{COUNTRY_CODE}",
        "appid": OPENWEATHER_API_KEY.strip(),
        "units": "metric",
    })
    url = f"{API_URL}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as e:
        # HTTPError must be caught before URLError (it is a subclass of it)
        if e.code == 401:
            print("ERROR: Invalid OpenWeather API key. Check OPENWEATHER_API_KEY.")
            print("       Note: brand-new keys can take up to a few hours to activate.")
        elif e.code == 404:
            print(f"ERROR: City '{CITY},{COUNTRY_CODE}' was not found. Check CITY and COUNTRY_CODE.")
        elif e.code == 429:
            print("ERROR: Too many requests to OpenWeather. Try again later.")
        else:
            print(f"ERROR: OpenWeather API failed with HTTP status {e.code}.")
    except urllib.error.URLError:
        print("ERROR: Could not connect to OpenWeather. Please check your internet connection.")
    except (socket.timeout, TimeoutError):
        print("ERROR: The connection to OpenWeather timed out. Please try again.")
    except json.JSONDecodeError:
        print("ERROR: OpenWeather returned data that could not be read.")
    except Exception as e:
        print(f"ERROR: Unexpected problem while contacting OpenWeather: {type(e).__name__}")
    return None


def parse_weather(data):
    """Pull the needed values out of the API response. Returns a dict or None."""
    try:
        tz = timezone(timedelta(seconds=data["timezone"]))

        def local_time(timestamp, fmt):
            return datetime.fromtimestamp(timestamp, tz=tz).strftime(fmt)

        main = data["main"]
        wind = data["wind"]
        condition = data["weather"][0]
        sys_info = data["sys"]

        report = {
            "location": data["name"],
            "country": sys_info["country"],
            "updated": local_time(data["dt"], "%A, %B %d, %Y at %I:%M %p"),
            "date_short": local_time(data["dt"], "%Y-%m-%d"),
            "temp": main["temp"],
            "feels_like": main["feels_like"],
            "temp_min": main["temp_min"],
            "temp_max": main["temp_max"],
            "humidity": main["humidity"],
            "pressure": main["pressure"],
            "wind_speed": wind["speed"],
            "wind_direction": degrees_to_compass(wind["deg"]) if "deg" in wind else "N/A",
            "condition": condition["main"],
            "description": condition["description"].title(),
            "cloudiness": data["clouds"]["all"],
            "visibility_km": data["visibility"] / 1000,
            "sunrise": local_time(sys_info["sunrise"], "%I:%M %p"),
            "sunset": local_time(sys_info["sunset"], "%I:%M %p"),
        }
        return report

    except (KeyError, IndexError, TypeError):
        print("ERROR: The weather data from OpenWeather is missing some expected information.")
        print("       Nothing was emailed. Please try again later.")
        return None


def build_email(report):
    """Create the EmailMessage with a plain-text and an HTML version."""
    rows = [
        ("Location", f"{report['location']}, {report['country']}"),
        ("Date and Time", report["updated"]),
        ("Temperature", f"{report['temp']:.1f} °C"),
        ("Feels Like", f"{report['feels_like']:.1f} °C"),
        ("Minimum Temperature", f"{report['temp_min']:.1f} °C"),
        ("Maximum Temperature", f"{report['temp_max']:.1f} °C"),
        ("Humidity", f"{report['humidity']} %"),
        ("Pressure", f"{report['pressure']} hPa"),
        ("Wind Speed", f"{report['wind_speed']:.1f} m/s"),
        ("Wind Direction", report["wind_direction"]),
        ("Weather Condition", report["condition"]),
        ("Description", report["description"]),
        ("Cloudiness", f"{report['cloudiness']} %"),
        ("Visibility", f"{report['visibility_km']:.1f} km"),
        ("Sunrise", report["sunrise"]),
        ("Sunset", report["sunset"]),
    ]

    # Plain-text fallback (for email apps that cannot show HTML)
    plain_text = "Daily Canada Weather Report\n\n"
    plain_text += "\n".join(f"{label}: {value}" for label, value in rows)

    # HTML version
    table_rows = ""
    for i, (label, value) in enumerate(rows):
        bg = "#f4f8fb" if i % 2 == 0 else "#ffffff"
        table_rows += (
            f'<tr style="background-color:{bg};">'
            f'<td style="padding:10px 14px;font-weight:bold;color:#2c3e50;'
            f'border-bottom:1px solid #e1e8ed;">{label}</td>'
            f'<td style="padding:10px 14px;color:#34495e;'
            f'border-bottom:1px solid #e1e8ed;">{value}</td></tr>'
        )

    html = f"""\
<html>
  <body style="margin:0;padding:20px;background-color:#eef2f5;font-family:Arial,Helvetica,sans-serif;">
    <table align="center" width="100%" cellpadding="0" cellspacing="0"
           style="max-width:600px;background-color:#ffffff;border-radius:8px;overflow:hidden;
                  border:1px solid #d5dde3;">
      <tr>
        <td style="background-color:#1f6fb2;padding:24px;text-align:center;">
          <h1 style="margin:0;color:#ffffff;font-size:24px;">Daily Canada Weather Report</h1>
          <p style="margin:6px 0 0;color:#d6e8f7;font-size:14px;">
            {report['location']}, {report['country']}
          </p>
        </td>
      </tr>
      <tr>
        <td style="padding:20px 24px 8px;text-align:center;">
          <div style="font-size:42px;font-weight:bold;color:#1f6fb2;">{report['temp']:.1f} °C</div>
          <div style="font-size:16px;color:#5d6d7e;">{report['description']}</div>
        </td>
      </tr>
      <tr>
        <td style="padding:12px 24px 24px;">
          <table width="100%" cellpadding="0" cellspacing="0"
                 style="border:1px solid #e1e8ed;border-collapse:collapse;font-size:14px;">
            {table_rows}
          </table>
        </td>
      </tr>
      <tr>
        <td style="background-color:#f4f8fb;padding:14px;text-align:center;
                   font-size:12px;color:#7f8c8d;">
          Data provided by OpenWeather. Sent automatically by your Python weather script.
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    msg = EmailMessage()
    msg["Subject"] = f"Daily Canada Weather Report - {CITY} - {report['date_short']}"
    msg["From"] = SENDER_EMAIL.strip()
    msg["To"] = RECEIVER_EMAIL.strip()
    msg.set_content(plain_text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_email(msg):
    """Send the email through Gmail SMTP over SSL (port 465). Returns True on success."""
    try:
        # App Passwords are often copied with spaces (e.g. "abcd efgh ijkl mnop"); remove them.
        password = APP_PASSWORD.replace(" ", "")
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
            server.login(SENDER_EMAIL.strip(), password)
            server.send_message(msg)
        return True

    except smtplib.SMTPAuthenticationError:
        print("ERROR: Gmail login failed. Check SENDER_EMAIL and APP_PASSWORD.")
        print("       Remember: you need a 16-character Gmail App Password")
        print("       (with 2-Step Verification turned on), not your normal password.")
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected,
            socket.gaierror, ConnectionError, TimeoutError, socket.timeout):
        print("ERROR: Could not connect to the Gmail SMTP server (smtp.gmail.com:465).")
        print("       Check your internet connection, firewall, or antivirus settings.")
    except smtplib.SMTPException as e:
        print(f"ERROR: Gmail rejected or failed to send the email ({type(e).__name__}).")
    except Exception as e:
        print(f"ERROR: Unexpected problem while sending the email: {type(e).__name__}")
    return False


def main():
    print("Starting Daily Canada Weather Report...")

    if not check_configuration():
        sys.exit(1)

    print(f"Fetching weather for {CITY}, {COUNTRY_CODE}...")
    data = fetch_weather()
    if data is None:
        sys.exit(1)

    report = parse_weather(data)
    if report is None:
        sys.exit(1)

    print("Weather data received. Building email...")
    message = build_email(report)

    print(f"Sending email to {RECEIVER_EMAIL}...")
    if send_email(message):
        print("SUCCESS: Weather report email sent!")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()