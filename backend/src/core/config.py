from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "AutoTrade API"
    DEBUG: bool = False
    PORT: int = 8080
    HOST: str = "0.0.0.0"
    AUTO_START: bool = False
    EXECUTION_TYPE: str = "simulation"  # "alpaca" o "simulation"
    TRADING_MODE: str = "paper"  # "paper" o "live"

    # Database Settings
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "trading_bot"
    DB_USER: str = "trading_user"
    DB_PASSWORD: str = "trading_password"

    # Strategy / Risk Settings
    STOP_LOSS_PCT: float = 0.0
    TAKE_PROFIT_PCT: float = 0.0
    MIN_ARB_EDGE_PCT: float = 0.03
    ARB_POSITION_SIZE_PCT: float = 0.50

    # Broker Credentials
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_TRADING_MODE: str = "paper"

    KALSHI_API_KEY_ID: str = ""
    KALSHI_PRIVATE_KEY_PATH: str = ""
    KALSHI_ENV: str = "demo"

    # Security / Auth
    SECRET_KEY: str = "super-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()
