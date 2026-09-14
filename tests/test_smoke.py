"""V5 smoke tests. Run after installing backend/requirements.txt with: python -m unittest discover tests"""
import unittest

class PackageSmokeTest(unittest.TestCase):
    def test_required_files_exist(self):
        import pathlib
        root=pathlib.Path(__file__).resolve().parents[1]
        required=[
            root/"backend/app/main.py",root/"backend/app/models.py",
            root/"backend/app/security.py",root/"frontend/index.html",root/"frontend/app.js"
        ]
        for p in required:self.assertTrue(p.exists(),str(p))

if __name__=="__main__": unittest.main()
