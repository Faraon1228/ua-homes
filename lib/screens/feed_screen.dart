import 'package:flutter/material.dart';
import 'package:google_maps_flutter/google_maps_flutter.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';

import '../services/file_helper.dart';

import '../models/models.dart';
import '../state/app_state.dart';
import 'story_viewer_screen.dart';

class FeedScreen extends StatefulWidget {
  const FeedScreen({super.key});

  @override
  State<FeedScreen> createState() => _FeedScreenState();
}

class _FeedScreenState extends State<FeedScreen> {
  final LatLng _center = const LatLng(50.4501, 30.5234);
  final TextEditingController _searchController = TextEditingController();
  final ImagePicker _picker = ImagePicker();

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _createStory(AppState appState) async {
    final selectedType = await showDialog<String>(
      context: context,
      builder: (context) {
        return SimpleDialog(
          backgroundColor: const Color(0xFF121212),
          title: const Text('Виберіть тип історії', style: TextStyle(color: Colors.white)),
          children: [
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, 'photo'),
              child: const Text('Фото', style: TextStyle(color: Colors.white)),
            ),
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, 'video'),
              child: const Text('Відео', style: TextStyle(color: Colors.white)),
            ),
          ],
        );
      },
    );

    if (selectedType == null) {
      return;
    }

    XFile? pickedFile;
    if (selectedType == 'photo') {
      pickedFile = await _picker.pickImage(source: ImageSource.gallery, imageQuality: 75);
    } else {
      pickedFile = await _picker.pickVideo(source: ImageSource.gallery);
    }

    if (pickedFile == null) {
      return;
    }

    final appDir = await getApplicationDocumentsDirectory();
    final savedPath = '${appDir.path}/${DateTime.now().millisecondsSinceEpoch}_${pickedFile.name}';
    await pickedFile.saveTo(savedPath);

    final newStory = Story(
      id: 'story_${DateTime.now().millisecondsSinceEpoch}',
      title: selectedType == 'photo' ? 'Нова фотоісторія' : 'Нове відео',
      author: 'Ви',
      authorAvatarUrl: null,
      location: 'Локально',
      description: selectedType == 'photo'
          ? 'Нова photo-історія з вашої бібліотеки.'
          : 'Нове відео, збережене на пристрої.',
      imagePath: selectedType == 'photo' ? savedPath : null,
      imageUrl: null,
      videoPath: selectedType == 'video' ? savedPath : null,
      videoUrl: null,
      likes: 0,
      views: 0,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );

    await appState.addStory(newStory);
    if (!mounted) return;

    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(selectedType == 'photo' ? 'Фотоісторію додано.' : 'Відеоісторію додано.')),
    );
  }

  void _openStory(Story story) {
    Navigator.push(
      context,
      MaterialPageRoute(builder: (context) => StoryViewerScreen(story: story)),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppState>(
      builder: (context, appState, child) {
        if (!appState.isLoaded) {
          return const Scaffold(body: Center(child: CircularProgressIndicator()));
        }

        return Scaffold(
          appBar: AppBar(
            backgroundColor: const Color(0xFF121212),
            title: Row(
              children: const [
                Icon(Icons.camera_alt_outlined, size: 24),
                SizedBox(width: 12),
                Text('DriveCommunity', style: TextStyle(letterSpacing: 0.8)),
              ],
            ),
            centerTitle: false,
            actions: [
              IconButton(icon: const Icon(Icons.search), onPressed: () {}),
              IconButton(
                icon: const Icon(Icons.send_outlined),
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Повідомлення ще не налаштовано.')),
                  );
                },
              ),
            ],
          ),
          body: Column(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  decoration: BoxDecoration(
                    color: const Color(0xFF1A1A1A),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: TextField(
                    controller: _searchController,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      icon: Icon(Icons.search, color: Colors.white70),
                      hintText: 'Пошук подій, маршрутів, друзів',
                      hintStyle: TextStyle(color: Colors.white54),
                      border: InputBorder.none,
                    ),
                  ),
                ),
              ),
              Container(
                height: 110,
                decoration: const BoxDecoration(
                  color: Color(0xFF121212),
                  border: Border(
                    bottom: BorderSide(color: Colors.white12),
                  ),
                ),
                child: ListView.builder(
                  scrollDirection: Axis.horizontal,
                  itemCount: appState.stories.length + 1,
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  itemBuilder: (context, index) {
                    if (index == 0) {
                      return _buildAddStoryTile(appState);
                    }
                    final story = appState.stories[index - 1];
                    return _buildStoryTile(story);
                  },
                ),
              ),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 12),
                  children: [
                    _buildMapCard(),
                    const SizedBox(height: 16),
                    _buildPostCard(
                      author: 'DriveCommunity',
                      caption: 'Найближча точка зустрічі в Києві. Підключайся, щоб поїхати разом.',
                      location: 'Київ • 20:00',
                    ),
                    const SizedBox(height: 16),
                    _buildPostCard(
                      author: 'RiderTeam',
                      caption: 'Вечірні маршрути в правому березі. Нові фото та відео скоро.',
                      location: 'Правий берег, Київ',
                    ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildAddStoryTile(AppState appState) {
    return Padding(
      padding: const EdgeInsets.only(right: 14),
      child: GestureDetector(
        onTap: () => _createStory(appState),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Stack(
              alignment: Alignment.center,
              children: [
                Container(
                  width: 62,
                  height: 62,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    border: Border.all(color: Colors.white24, width: 1.5),
                  ),
                ),
                const CircleAvatar(
                  radius: 26,
                  backgroundColor: Color(0xFF2A2A2A),
                  child: Icon(Icons.person, color: Colors.white),
                ),
                Positioned(
                  bottom: 0,
                  right: 0,
                  child: Container(
                    width: 22,
                    height: 22,
                    decoration: const BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: LinearGradient(
                        colors: [Color(0xFFDE0046), Color(0xFFF7A34B)],
                      ),
                    ),
                    child: const Icon(Icons.add, size: 16, color: Colors.white),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 6),
            const Text('Ваша історія', style: TextStyle(fontSize: 11, color: Colors.white70)),
          ],
        ),
      ),
    );
  }

  Widget _buildStoryTile(Story story) {
    final isTestEnvironment = bool.fromEnvironment('FLUTTER_TEST');
    final hasLocalImage = story.imagePath != null && localFileExists(story.imagePath!);
    final hasRemoteImage = !isTestEnvironment && story.imageUrl != null;

    Widget avatarContent;
    if (hasLocalImage) {
      avatarContent = CircleAvatar(
        radius: 26,
        backgroundColor: const Color(0xFF2A2A2A),
        backgroundImage: localFileImage(story.imagePath!),
      );
    } else if (hasRemoteImage) {
      avatarContent = CircleAvatar(
        radius: 26,
        backgroundColor: const Color(0xFF2A2A2A),
        child: ClipOval(
          child: Image.network(
            story.imageUrl!,
            fit: BoxFit.cover,
            width: 52,
            height: 52,
            errorBuilder: (context, error, stackTrace) {
              return const Center(child: Icon(Icons.person, color: Colors.white));
            },
          ),
        ),
      );
    } else {
      avatarContent = const CircleAvatar(
        radius: 26,
        backgroundColor: Color(0xFF2A2A2A),
        child: Icon(Icons.person, color: Colors.white),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(right: 14),
      child: GestureDetector(
        onTap: () => _openStory(story),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Container(
              width: 62,
              height: 62,
              decoration: const BoxDecoration(
                shape: BoxShape.circle,
                gradient: LinearGradient(
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                  colors: [Color(0xFFDE0046), Color(0xFFF7A34B)],
                ),
              ),
              padding: const EdgeInsets.all(3),
              child: Stack(
                alignment: Alignment.center,
                children: [
                  avatarContent,
                  if (story.isVideo)
                    const Icon(Icons.play_circle_outline, color: Colors.white70, size: 24),
                ],
              ),
            ),
            const SizedBox(height: 6),
            Text(story.title, style: const TextStyle(fontSize: 11, color: Colors.white70)),
          ],
        ),
      ),
    );
  }

  Widget _buildMapCard() {
    return Card(
      color: const Color(0xFF1E1E1E),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ClipRRect(
            borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
            child: SizedBox(
              height: 220,
              child: GoogleMap(
                onMapCreated: (GoogleMapController controller) {},
                initialCameraPosition: CameraPosition(target: _center, zoom: 12.0),
                markers: {
                  Marker(
                    markerId: const MarkerId('spot_1'),
                    position: _center,
                    infoWindow: const InfoWindow(
                      title: 'Точка збору спільноти 🏍️',
                      snippet: 'Сьогодні о 20:00',
                    ),
                  ),
                },
                myLocationButtonEnabled: false,
                zoomControlsEnabled: false,
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(14.0),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: const [
                      Text('Точка збору спільноти', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                      SizedBox(height: 4),
                      Text('Київ • 20:00 • 32 учасники', style: TextStyle(color: Colors.white70)),
                    ],
                  ),
                ),
                ElevatedButton(
                  style: ElevatedButton.styleFrom(backgroundColor: const Color(0xFFDE0046)),
                  onPressed: () {},
                  child: const Text('ЙДУ'),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPostCard({
    required String author,
    required String caption,
    required String location,
  }) {
    return Card(
      color: const Color(0xFF171717),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.all(14.0),
            child: Row(
              children: [
                Container(
                  width: 40,
                  height: 40,
                  decoration: const BoxDecoration(
                    shape: BoxShape.circle,
                    color: Color(0xFF2A2A2A),
                  ),
                  child: const Icon(Icons.person, color: Colors.white),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(author, style: const TextStyle(fontWeight: FontWeight.bold)),
                      const SizedBox(height: 2),
                      Text(location, style: const TextStyle(color: Colors.white70, fontSize: 12)),
                    ],
                  ),
                ),
                const Icon(Icons.more_horiz, color: Colors.white70),
              ],
            ),
          ),
          Container(
            height: 180,
            decoration: BoxDecoration(
              color: Colors.grey.shade900,
              borderRadius: const BorderRadius.vertical(bottom: Radius.circular(20)),
            ),
            child: const Center(
              child: Icon(Icons.location_on_outlined, color: Colors.white24, size: 52),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(14.0),
            child: Text(caption, style: const TextStyle(color: Colors.white70)),
          ),
        ],
      ),
    );
  }
}
