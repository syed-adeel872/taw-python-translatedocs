"""Application error types with safe, user-facing messages."""

from __future__ import annotations


class AppError(Exception):
    """Base class for errors that are safe to show to the user."""

    status_code = 400
    default_message = "The request could not be processed."

    def __init__(self, message: str | None = None) -> None:
        self.user_message = message or self.default_message
        super().__init__(self.user_message)


class InvalidUploadError(AppError):
    default_message = "The uploaded file is not valid."


class UnsupportedFileTypeError(InvalidUploadError):
    default_message = "Unsupported file type. Upload a DOCX or PDF document."


class FileTooLargeError(InvalidUploadError):
    status_code = 413
    default_message = "The uploaded file is too large."


class CorruptedDocumentError(InvalidUploadError):
    default_message = "The document is corrupted or cannot be opened."


class PasswordProtectedError(InvalidUploadError):
    default_message = (
        "Password-protected PDFs are not supported. Remove the password and try again."
    )


class EmptyDocumentError(AppError):
    default_message = "The document contains no translatable text."


class ScannedPdfError(EmptyDocumentError):
    default_message = (
        "No selectable text was found in this PDF. Scanned documents need OCR, "
        "which is not supported by this free application."
    )


class DocumentProcessingError(AppError):
    default_message = "The document could not be processed."


class TranslationError(AppError):
    status_code = 502
    default_message = "Translation failed. Please try again."


class RateLimitError(TranslationError):
    default_message = (
        "The translation provider is rate-limiting requests. "
        "Wait a few minutes and try again."
    )


class TransientTranslationError(TranslationError):
    default_message = (
        "The translation provider is temporarily unavailable. Please try again shortly."
    )


class ProviderConfigurationError(TranslationError):
    default_message = (
        "The translation provider is not configured. "
        "Check the server environment variables."
    )


class MalformedTranslationResponse(TranslationError):
    default_message = (
        "The translation provider returned a response the application could not understand."
    )
