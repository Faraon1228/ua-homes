import 'dart:io';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final ImagePicker _picker = ImagePicker();
  File? _avatarImage;
  String _username = 'Олександр_R1';
  String _location = 'Київ • правий берег';

  Future<void> _pickAvatar() async {
    final XFile? pickedFile = await _picker.pickImage(source: ImageSource.gallery);
    if (pickedFile != null && mounted) {
      setState(() {
        _avatarImage = File(pickedFile.path);
      });
    }
  }

  Future<void> _editProfile() async {
    final result = await showDialog<Map<String, String>>(
      context: context,
      builder: (context) {
        final usernameController = TextEditingController(text: _username);
        final locationController = TextEditingController(text: _location);
        return AlertDialog(
          backgroundColor: const Color(0xFF121212),
          title: const Text('Редагувати профіль', style: TextStyle(color: Colors.white)),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: usernameController,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  hintText: 'Ім’я',
                  hintStyle: TextStyle(color: Colors.white54),
                ),
              ),
              const SizedBox(height: 10),
              TextField(
                controller: locationController,
                style: const TextStyle(color: Colors.white),
                decoration: const InputDecoration(
                  hintText: 'Місцезнаходження',
                  hintStyle: TextStyle(color: Colors.white54),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Відмінити', style: TextStyle(color: Colors.white70)),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context, {
                'username': usernameController.text.trim(),
                'location': locationController.text.trim(),
              }),
              child: const Text('Зберегти', style: TextStyle(color: Color(0xFFDE0046))),
            ),
          ],
        );
      },
    );

    if (result != null && mounted) {
      setState(() {
        _username = result['username']?.isEmpty == true ? _username : result['username']!;
        _location = result['location']?.isEmpty == true ? _location : result['location']!;
      });
    }
  }

  Widget _buildProfileStat(String value, String label) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Text(value, style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 18)),
          const SizedBox(height: 4),
          Text(label, style: const TextStyle(color: Colors.white70, fontSize: 12)),
        ],
      ),
    );
  }

  Widget _buildGarageTile(String title, String subtitle, IconData icon) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1C1C1C),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: const Color(0xFF2A2A2A),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Icon(icon, color: Colors.amber),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
                const SizedBox(height: 4),
                Text(subtitle, style: const TextStyle(color: Colors.white70)),
              ],
            ),
          ),
          const Icon(Icons.arrow_forward_ios, size: 18, color: Colors.white70),
        ],
      ),
    );
  }

  Widget _buildHighlightTile(String label) {
    return Padding(
      padding: const EdgeInsets.only(right: 12),
      child: Column(
        children: [
          Container(
            width: 70,
            height: 70,
            decoration: const BoxDecoration(
              shape: BoxShape.circle,
              gradient: LinearGradient(
                colors: [Color(0xFFDE0046), Color(0xFFF7A34B)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
            ),
            child: const Padding(
              padding: EdgeInsets.all(4.0),
              child: CircleAvatar(
                backgroundColor: Color(0xFF121212),
                child: Icon(Icons.bookmark_border, color: Colors.white),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Text(label, style: const TextStyle(color: Colors.white70, fontSize: 12)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Профіль'),
        backgroundColor: const Color(0xFF121212),
        actions: [
          IconButton(icon: const Icon(Icons.more_horiz), onPressed: () {}),
        ],
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                GestureDetector(
                  onTap: _pickAvatar,
                  child: CircleAvatar(
                    radius: 45,
                    backgroundColor: Colors.grey.shade800,
                    backgroundImage: _avatarImage != null ? FileImage(_avatarImage!) : null,
                    child: _avatarImage == null
                        ? const Icon(Icons.person, size: 40, color: Colors.white)
                        : null,
                  ),
                ),
                const SizedBox(width: 18),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(_username, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
                      const SizedBox(height: 6),
                      Text(_location, style: const TextStyle(color: Colors.white70)),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _buildProfileStat('32', 'Пости'),
                _buildProfileStat('1.2K', 'Підписники'),
                _buildProfileStat('298', 'Підписки'),
              ],
            ),
            const SizedBox(height: 18),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white,
                      side: const BorderSide(color: Colors.white24),
                    ),
                    onPressed: _editProfile,
                    child: const Text('Редагувати профіль'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white,
                      side: const BorderSide(color: Colors.white24),
                    ),
                    onPressed: _pickAvatar,
                    child: const Text('Додати фото'),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 22),
            const Text('Гараж', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            _buildGarageTile('Yamaha YZF-R1 (2020)', '1000cc • Спортбайк', Icons.two_wheeler),
            const SizedBox(height: 12),
            _buildGarageTile('BMW M3 E92', '4.0L V8 • Купе', Icons.directions_car),
            const SizedBox(height: 16),
            const Text('Stories Highlights', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            SizedBox(
              height: 120,
              child: ListView(
                scrollDirection: Axis.horizontal,
                children: [
                  _buildHighlightTile('Подорожі'),
                  _buildHighlightTile('Тюнінг'),
                  _buildHighlightTile('Мото'),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}
