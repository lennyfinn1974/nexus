"""Tests for the encryption module."""



class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self, tmp_base_dir):
        from storage.encryption import decrypt, encrypt, init

        init(str(tmp_base_dir))
        original = "sk-ant-super-secret-key-12345"
        encrypted = encrypt(original)
        assert encrypted != original
        decrypted = decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_empty_string(self, tmp_base_dir):
        from storage.encryption import decrypt, encrypt, init

        init(str(tmp_base_dir))
        encrypted = encrypt("")
        decrypted = decrypt(encrypted)
        assert decrypted == ""

    def test_encrypt_unicode(self, tmp_base_dir):
        from storage.encryption import decrypt, encrypt, init

        init(str(tmp_base_dir))
        original = "Secret with unicode chars"
        encrypted = encrypt(original)
        decrypted = decrypt(encrypted)
        assert decrypted == original

    def test_different_inputs_different_outputs(self, tmp_base_dir):
        from storage.encryption import encrypt, init

        init(str(tmp_base_dir))
        enc1 = encrypt("secret-one")
        enc2 = encrypt("secret-two")
        assert enc1 != enc2
