"""Test local inference contract without requiring Metal or loading weights."""
import unittest
from unittest.mock import Mock, patch
import numpy as np

from representations.local_provider import MLXProvider
from representations.providers import ProviderError


class LocalProviderTests(unittest.TestCase):
    def provider(self):
        p = MLXProvider.__new__(MLXProvider)
        p.config = {'max_input_bytes':100, 'max_input_tokens':16,'role_prompts':{'query':'Q: ','document':'D: '},
                    'dimensions':4,'batch_size':2}
        p.model = Mock()
        p.model.args.max_seq_length = 16
        p.model.encode.return_value = np.ones((2,4), dtype=np.float32)
        p.tokenizer = Mock()
        p.tokenizer.encode_batch.return_value = [Mock(ids=[1,2,3]), Mock(ids=[1,2])]
        return p

    def test_role_prefixes_and_ordered_float_output(self):
        provider = self.provider()
        arrays, usage = provider.embed(['first', 'second'], 'query')
        provider.tokenizer.encode_batch.assert_called_once_with(['Q: first', 'Q: second'])
        self.assertEqual(provider.model.encode.call_args.kwargs['prompt_name'], 'query')
        self.assertEqual(usage['input_tokens_with_role_prefix'], 5)
        self.assertEqual(len(arrays), 2)
        self.assertTrue(all(a.dtype == np.float32 for a in arrays))

    def test_no_silent_truncation(self):
        provider = self.provider()
        provider.tokenizer.encode_batch.return_value = [Mock(ids=list(range(17)))]
        with self.assertRaisesRegex(ProviderError, 'exceeds_context'):
            provider.embed(['first'], 'document')
        provider.model.encode.assert_not_called()

    def test_unsupported_host_abstains(self):
        with patch('representations.local_provider.platform.system', return_value='Linux'):
            with self.assertRaisesRegex(ProviderError, 'apple_silicon'):
                MLXProvider({})
