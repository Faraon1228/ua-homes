import 'package:flutter/material.dart';
import 'package:hive_flutter/hive_flutter.dart';
import 'package:provider/provider.dart';

import 'models/adapters.dart';
import 'repositories/data_repository.dart';
import 'screens/chat_screen.dart';
import 'screens/feed_screen.dart';
import 'screens/profile_screen.dart';
import 'screens/real_estate_demo_screen.dart';
import 'services/hive_storage_service.dart';
import 'services/remote_sync_service.dart';
import 'state/app_state.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Hive.initFlutter();
  Hive.registerAdapter(StoryAdapter());
  Hive.registerAdapter(ChatMessageAdapter());
  Hive.registerAdapter(ChatThreadAdapter());

  runApp(const DriveCommunityApp());
}

class DriveCommunityApp extends StatelessWidget {
  const DriveCommunityApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ChangeNotifierProvider<AppState>(
      create: (_) => AppState(
        repository: DataRepository(
          localStorage: HiveStorageService(),
          remoteSync: RemoteSyncService(),
        ),
      )..load(),
      child: MaterialApp(
        title: 'DriveCommunity',
        debugShowCheckedModeBanner: false,
        theme: ThemeData.dark().copyWith(
          scaffoldBackgroundColor: const Color(0xFF090909),
          primaryColor: Colors.white,
          appBarTheme: const AppBarTheme(
            backgroundColor: Color(0xFF121212),
            elevation: 0,
            iconTheme: IconThemeData(color: Colors.white),
            titleTextStyle: TextStyle(
              color: Colors.white,
              fontSize: 20,
              fontWeight: FontWeight.bold,
            ),
          ),
        ),
        home: const MainHomeScreen(),
      ),
    );
  }
}

class MainHomeScreen extends StatefulWidget {
  const MainHomeScreen({super.key});

  @override
  State<MainHomeScreen> createState() => _MainHomeScreenState();
}

class _MainHomeScreenState extends State<MainHomeScreen> {
  int _currentIndex = 0;

  static const List<Widget> _screens = [
    FeedScreen(),
    ChatScreen(),
    RealEstateDemoScreen(),
    ProfileScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: _screens[_currentIndex],
      bottomNavigationBar: BottomNavigationBar(
        type: BottomNavigationBarType.fixed,
        currentIndex: _currentIndex,
        selectedItemColor: Colors.white,
        unselectedItemColor: Colors.grey,
        backgroundColor: const Color(0xFF121212),
        onTap: (index) {
          setState(() {
            _currentIndex = index;
          });
        },
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.home_outlined), label: 'Головна'),
          BottomNavigationBarItem(icon: Icon(Icons.chat_bubble_outline), label: 'Чати'),
          BottomNavigationBarItem(icon: Icon(Icons.home_work_outlined), label: 'Демо'),
          BottomNavigationBarItem(icon: Icon(Icons.person_outline), label: 'Профіль'),
        ],
      ),
    );
  }
}
