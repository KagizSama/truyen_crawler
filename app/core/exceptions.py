class CrawlerError(Exception):
    """Base exception for crawler errors."""
    pass

class NetworkError(CrawlerError):
    """Raised when a network request fails after retries."""
    pass

class ParsingError(CrawlerError):
    """Raised when the parser fails to find expected content."""
    pass

class RateLimitError(CrawlerError):
    """Raised when the crawler hits a rate limit."""
    pass
