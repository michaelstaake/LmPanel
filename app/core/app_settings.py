from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings

DEFAULT_SETTINGS_ID = 1


def get_or_create_app_settings(db: Session) -> AppSettings:
    settings = db.query(AppSettings).filter(AppSettings.id == DEFAULT_SETTINGS_ID).first()
    if settings is None:
        settings = AppSettings(id=DEFAULT_SETTINGS_ID)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings