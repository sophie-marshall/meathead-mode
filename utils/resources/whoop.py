import logging
import sys
import json
import secrets
import socketserver
from urllib.parse import urlencode
import webbrowser
import requests

from ..auth import OAuthCallbackHandler

## -- LOGGING CONFIG -- ##
logging.basicConfig(
    level=logging.DEBUG,  # Show DEBUG and above
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


## -- RESOURCE DEFINITION -- ##
class Whoop:

    # class level vars
    SCOPES = [
        "read:recovery",
        "read:cycles",
        "read:workout",
        "read:sleep",
        "read:profile",
        "offline",
    ]
    STATE = secrets.token_urlsafe(16)
    BASE_URL = "https://api.prod.whoop.com/developer/v2"

    @classmethod
    def _fetch_access_token(cls, config_filepath: str = "config.json") -> str | None:
        config = cls._load_config(config_filepath)

        if config.get("access_token") is None:
            logger.error(
                "Access token not found in config. Please run init_auth_flow first."
            )
            return None
        return config.get("access_token")

    @classmethod
    def _load_config(cls, config_filepath: str = "config.json") -> dict:
        """
        Loads the WHOOP config json file. If not set up, ensure a the file exists and contains the
        following

        {
            "client_id": "",
            "client_secret": "",
            "redirect_uri": "",
            "access_token": null,
            "refresh_token": null
        }

        Where client_id, client_secret, and redirect_uri are obtained/set via WHOOP developer dashboard
        on a by-project basis

        Access and refresh tokens are obtained via OAuth2 flow and can be null initially
        """
        try:
            with open(config_filepath, "r") as f:
                config = json.load(f)
            logger.debug(f"Configuration loaded from {config_filepath}")
            return config
        except FileNotFoundError:
            logger.error(f"Configuration file {config_filepath} not found.")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {config_filepath}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Unexpected error loading config: {e}")
            return {}

    @classmethod
    def _get_callback_code(
        cls, port: int = 8080, config_filepath: str = "config.json"
    ) -> str:
        with socketserver.TCPServer(("", port), OAuthCallbackHandler) as httpd:
            # load params
            params = cls._load_config()

            # make auth specific params object
            auth_params = {
                "client_id": params["client_id"],
                "redirect_uri": params["redirect_uri"],
                "scope": " ".join(cls.SCOPES),
                "state": cls.STATE,
                "response_type": "code",
            }

            # build auth url from params
            url = (
                f"https://api.prod.whoop.com/oauth/oauth2/auth?{urlencode(auth_params)}"
            )

            # redirect for user auth
            webbrowser.open(url)
            httpd.handle_request()

            return OAuthCallbackHandler.callback_code

    @classmethod
    def init_auth_flow(cls, config_filepath: str = "config.json"):
        """
        For first time users, initialize a full OAuth2 authetication flow to obtain access
        and refresh tokens. On authorization, the config.json file will be updated with the
        obtained values.
        """

        # load params
        params = cls._load_config(config_filepath)

        # add grant type and code
        params["grant_type"] = "authorization_code"
        params["code"] = cls._get_callback_code(config_filepath)

        # request tokens
        res = requests.post(
            url="https://api.prod.whoop.com/oauth/oauth2/token", data=params
        )
        res.raise_for_status()

        # remove request specific attributes
        params.pop("grant_type")
        params.pop("code")

        # update config with new values
        params["access_token"] = res.json().get("access_token")
        params["refresh_token"] = res.json().get("refresh_token")

        with open(config_filepath, "w") as f:
            json.dump(params, f, indent=4)

        logger.info(
            "Authentication flow complete. Access and refresh tokens saved to config."
        )

    @classmethod
    def check_config(cls, config_filepath: str = "config.json") -> None:
        # load config
        config = cls._load_config(config_filepath)

        required_keys = [
            "client_id",
            "client_secret",
            "redirect_uri",
            "access_token",
            "refresh_token",
        ]
        missing_keys = [
            key
            for key in required_keys
            if key not in config or config[key] in (None, "")
        ]
        if missing_keys:
            logger.warning(
                f"Missing or empty keys in config: {', '.join(missing_keys)}"
            )
        else:
            logger.info("All required configuration keys are present.")
        return None

    @classmethod
    def refresh_access_tokens(cls, config_filepath: str = "config.json") -> None:
        params = cls._load_config(config_filepath)

        # set request params
        refresh_params = {
            "grant_type": "refresh_token",
            "client_id": params.get("client_id"),
            "client_secret": params.get("client_secret"),
            "scope": "offline",
            "refresh_token": params.get("refresh_token"),
        }

        # request new tokens
        res = requests.post(
            url="https://api.prod.whoop.com/oauth/oauth2/token", data=refresh_params
        )

        params["access_token"] = res.json().get("access_token")
        params["refresh_token"] = res.json().get("refresh_token")

        with open(config_filepath, "w") as f:
            json.dump(params, f, indent=4)

    @classmethod
    def get_records(cls, record_type: str, config_filepath: str) -> list[dict]:
        # set url based on record
        if record_type == "sleep":
            url = f"{cls.BASE_URL}/activity/sleep"
        elif record_type == "workout":
            url = f"{cls.BASE_URL}/activity/workout"
        elif record_type == "profile":
            url = f"{cls.BASE_URL}/user/profile/basic"
        elif record_type == "recovery":
            url = f"{cls.BASE_URL}/recovery"
        else:
            logger.error(f"Invalid record type: {record_type}")

        res = requests.get(
            url=url,
            headers={
                "Authorization": f"Bearer {cls._fetch_access_token(config_filepath)}"
            },
        )

        if res.status_code == 401:
            logger.warning("Access token expired, refreshing...")
            cls.refresh_access_tokens(config_filepath)
            res = requests.get(
                url=url,
                headers={
                    "Authorization": f"Bearer {cls._fetch_access_token(config_filepath)}"
                },
            )

        if res.status_code != 200:
            logger.error(f"Error fetching {record_type} records: {res.text}")
            return []
        else:
            if record_type == "profile":
                return [res.json()]
            return res.json().get("records", [])
