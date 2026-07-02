## 1. Add Beijing time utility function

- [x] 1.1 Add `beijing_now()` function to `raganything/utils/_general.py` using `datetime.now(timezone(timedelta(hours=8)))`
- [x] 1.2 Export `beijing_now` from `raganything/utils/__init__.py` (add to imports and `__all__`)

## 2. Update doc_processor.py

- [x] 2.1 Import `beijing_now` from `raganything.utils` in `raganything/processor/doc_processor.py`
- [x] 2.2 Replace `_current_doc_status_timestamp()` body to call `beijing_now()` instead of `time.strftime(..., time.gmtime())`
- [x] 2.3 Replace `time.strftime("%Y-%m-%dT%H:%M:%S+00:00")` with `beijing_now()` at line 828 (failure status creation)
- [x] 2.4 Replace `time.strftime("%Y-%m-%dT%H:%M:%S+00:00")` with `beijing_now()` at line 836 (failure status update)

## 3. Update multimodal_processor.py

- [x] 3.1 Import `beijing_now` from `raganything.utils` in `raganything/processor/multimodal_processor.py`
- [x] 3.2 Replace `time.strftime("%Y-%m-%dT%H:%M:%S+00:00")` with `beijing_now()` at line 337

## 4. Update chunk_processor.py

- [x] 4.1 Import `beijing_now` from `raganything.utils` in `raganything/processor/chunk_processor.py`
- [x] 4.2 Replace `time.strftime("%Y-%m-%dT%H:%M:%S+00:00")` with `beijing_now()` at line 426

## 5. Verification

- [x] 5.1 Run existing tests to ensure no regressions: `pytest tests/ -x -q`
- [x] 5.2 Manually verify that a newly uploaded document shows Beijing time (UTC+8) in `updated_at`
