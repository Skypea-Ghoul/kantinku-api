import 'package:flutter/material.dart';

void main(){
  runApp(MyApps());
}

class MyApps extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        backgroundColor: Colors.white,
        appBar: AppBar(
          title: Text('My App',
          style: TextStyle(
            color: Colors.white,
            fontFamily: 'Arial',
            fontSize: 24,
          ),
          ),
          backgroundColor: Colors.blue,
        ),
        body: Center(
          child: Text('Hello, World!'),
        ),
      ),
    );
  }
}