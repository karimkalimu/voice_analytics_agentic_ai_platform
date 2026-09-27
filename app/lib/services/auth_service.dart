import 'package:firebase_auth/firebase_auth.dart';

class AuthService {
  static final FirebaseAuth _auth = FirebaseAuth.instance;

  static Stream<User?> get authStateChanges => _auth.authStateChanges();

  static Future<({String uid, String token})> credentials() async {
    final user = _auth.currentUser;
    if (user == null) throw StateError('Not signed in.');
    final token = await user.getIdToken();
    if (token == null || token.isEmpty) {
      throw StateError('No Firebase ID token available.');
    }
    return (uid: user.uid, token: token);
  }

  static Future<void> login(String email, String password) async {
    await _auth.signInWithEmailAndPassword(email: email, password: password);
  }

  static Future<void> signup(String email, String password) async {
    await _auth.createUserWithEmailAndPassword(
      email: email,
      password: password,
    );
  }

  static Future<void> logout() => _auth.signOut();
}
