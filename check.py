import time
from typing import Dict
class TokenBucket:    """    Token bucket rate limiter.
Attributes:        capacity (int): The maximum number of tokens in the bucket.        refill_rate (float): The rate at which tokens are refilled per second.        last_refill (float): The time of the last refill.        tokens (int): The current number of tokens in the bucket.    """
def __init__(self, capacity: int, refill_rate: float):        """        Initializes the token bucket.
Args:            capacity (int): The maximum number of tokens in the bucket.            refill_rate (float): The rate at which tokens are refilled per second.
Raises:            ValueError: If the refill rate is zero.        """        if refill_rate == 0:            raise ValueError("Refill rate cannot be zero")        self.capacity = capacity        self.refill_rate = refill_rate        self.last_refill = time.time()        self.tokens = capacity
def consume(self, num_tokens: int) -> bool:        """        Consumes a certain number of tokens from the bucket.
Args:            num_tokens (int): The number of tokens to consume.
Returns:            bool: Whether the consumption was successful.
Raises:            ValueError: If the number of tokens is negative or exceeds the bucket capacity.        """        if num_tokens < 0:            raise ValueError("Number of tokens cannot be negative")        if num_tokens > self.capacity:            raise ValueError("Number of tokens exceeds bucket capacity")        current_time = time.time()        elapsed_time = current_time - self.last_refill        self.last_refill = current_time        self.tokens = min(self.capacity, self.tokens + elapsed_time * self.refill_rate)        if self.tokens < num_tokens:            return False        self.tokens -= num_tokens        return True
class RateLimiter:    """    Rate limiter using a token bucket.
Attributes:        bucket (TokenBucket): The token bucket.    """
def __init__(self, capacity: int, refill_rate: float):        """        Initializes the rate limiter.
Args:            capacity (int): The maximum number of requests per second.            refill_rate (float): The rate at which tokens are refilled per second.        """        self.bucket = TokenBucket(capacity, refill_rate)
def allow_request(self) -> bool:        """        Allows a request if the bucket has enough tokens.
Returns:            bool: Whether the request is allowed.
Notes:            This method consumes a single token from the bucket.        """        return self.bucket.consume(TOKEN_CONSUMPTION)
class Constants:    """    Constants used throughout the code.    """    TOKEN_CONSUMPTION = 1    NUM_REQUESTS = 10    ALLOWED_REQUEST_MESSAGE = "Request {i+1} allowed"    BLOCKED_REQUEST_MESSAGE = "Request {i+1} blocked"
def main():    # Create a rate limiter that allows 5 requests per second    limiter = RateLimiter(5, 5.0)
# Simulate NUM_REQUESTS requests    for i in range(Constants.NUM_REQUESTS):        if limiter.allow_request():            print(f"{Constants.ALLOWED_REQUEST_MESSAGE.format(i=i)}")        else:            print(f"{Constants.BLOCKED_REQUEST_MESSAGE.format(i=i)}")
