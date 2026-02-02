//! Shared exponential backoff retry logic for LLM providers.

use std::future::Future;
use std::time::Duration;

use backoff::backoff::Backoff;
use backoff::ExponentialBackoff;

/// Configuration: 3 total attempts, base 1s, max 30s.
pub const MAX_ATTEMPTS: u32 = 3;
const INITIAL_INTERVAL_SECS: u64 = 1;
const MAX_INTERVAL_SECS: u64 = 30;

/// Retry an async operation with exponential backoff.
///
/// `attempt` is called up to `MAX_ATTEMPTS` times. On each failure, the
/// returned error is stashed and the task sleeps for an exponentially
/// increasing duration before the next attempt.
///
/// `wrap_exhausted` converts the last error into the appropriate
/// `RetriesExhausted` variant for the caller's error type.
pub async fn retry_with_backoff<T, E, Fut, F, W>(
    mut attempt: F,
    wrap_exhausted: W,
) -> Result<T, E>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = Result<T, E>>,
    W: FnOnce(E) -> E,
{
    let mut backoff = ExponentialBackoff {
        initial_interval: Duration::from_secs(INITIAL_INTERVAL_SECS),
        max_interval: Duration::from_secs(MAX_INTERVAL_SECS),
        max_elapsed_time: None,
        ..Default::default()
    };

    let mut attempts = 0;
    let mut last_error = None;

    while attempts < MAX_ATTEMPTS {
        attempts += 1;

        match attempt().await {
            Ok(value) => return Ok(value),
            Err(e) => {
                last_error = Some(e);

                if attempts < MAX_ATTEMPTS
                    && let Some(wait_duration) = backoff.next_backoff()
                {
                    tokio::time::sleep(wait_duration).await;
                }
            }
        }
    }

    Err(wrap_exhausted(
        last_error.expect("last_error should be Some after failed retries"),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::Arc;

    #[derive(Debug, PartialEq)]
    enum TestError {
        Transient(String),
        RetriesExhausted(Box<TestError>),
    }

    #[tokio::test(start_paused = true)]
    async fn test_retry_succeeds_on_first_attempt() {
        let result: Result<&str, TestError> =
            retry_with_backoff(|| async { Ok("ok") }, |e| TestError::RetriesExhausted(Box::new(e)))
                .await;
        assert_eq!(result.unwrap(), "ok");
    }

    #[tokio::test(start_paused = true)]
    async fn test_retry_exhausts_after_max_attempts() {
        let count = Arc::new(AtomicU32::new(0));
        let count_clone = count.clone();

        let result: Result<(), TestError> = retry_with_backoff(
            move || {
                let c = count_clone.clone();
                async move {
                    c.fetch_add(1, Ordering::SeqCst);
                    Err(TestError::Transient("fail".to_string()))
                }
            },
            |e| TestError::RetriesExhausted(Box::new(e)),
        )
        .await;

        assert!(matches!(result, Err(TestError::RetriesExhausted(_))));
        assert_eq!(count.load(Ordering::SeqCst), MAX_ATTEMPTS);
    }

    #[tokio::test(start_paused = true)]
    async fn test_retry_succeeds_after_failures() {
        let count = Arc::new(AtomicU32::new(0));
        let count_clone = count.clone();

        let result: Result<&str, TestError> = retry_with_backoff(
            move || {
                let c = count_clone.clone();
                async move {
                    let n = c.fetch_add(1, Ordering::SeqCst);
                    if n < 2 {
                        Err(TestError::Transient("transient".to_string()))
                    } else {
                        Ok("recovered")
                    }
                }
            },
            |e| TestError::RetriesExhausted(Box::new(e)),
        )
        .await;

        assert_eq!(result.unwrap(), "recovered");
        assert_eq!(count.load(Ordering::SeqCst), 3);
    }
}
